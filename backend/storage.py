"""Small SQLite persistence layer for encrypted CHAABI vault records."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
from typing import Any


class VaultAlreadyExistsError(RuntimeError):
    """Raised when enrollment tries to replace an existing vault implicitly."""


class AccountAlreadyExistsError(RuntimeError):
    """Raised when signup tries to reuse an existing account identifier."""


class ActiveUserConflictError(RuntimeError):
    """Raised when another user still owns the single edge-device session."""


def _database_path() -> Path:
    configured = os.getenv("CHAABI_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).with_name("chaabi.db")


def initialize_database() -> None:
    path = _database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS voice_vaults (
                user_id TEXT PRIMARY KEY,
                vault_json TEXT NOT NULL,
                dsp_version TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                user_id TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS device_session (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                idle_expires_at INTEGER NOT NULL,
                absolute_expires_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES accounts(user_id)
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def save_vault(
    user_id: str,
    vault: dict[str, Any],
    dsp_version: str,
    created_at: int,
    *,
    replace_existing: bool = False,
) -> None:
    initialize_database()
    connection = sqlite3.connect(_database_path())
    try:
        statement = (
            """
            INSERT INTO voice_vaults(user_id, vault_json, dsp_version, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                vault_json = excluded.vault_json,
                dsp_version = excluded.dsp_version,
                created_at = excluded.created_at
            """
            if replace_existing
            else """
            INSERT INTO voice_vaults(user_id, vault_json, dsp_version, created_at)
            VALUES (?, ?, ?, ?)
            """
        )
        try:
            connection.execute(
                statement,
                (
                    user_id,
                    json.dumps(vault, separators=(",", ":")),
                    dsp_version,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise VaultAlreadyExistsError(
                "A vault already exists for this user."
            ) from exc
        connection.commit()
    finally:
        connection.close()


def load_vault(user_id: str) -> dict[str, Any] | None:
    initialize_database()
    connection = sqlite3.connect(_database_path())
    try:
        row = connection.execute(
            "SELECT vault_json FROM voice_vaults WHERE user_id = ?", (user_id,)
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return json.loads(str(row[0]))


def vault_exists(user_id: str) -> bool:
    initialize_database()
    connection = sqlite3.connect(_database_path())
    try:
        row = connection.execute(
            "SELECT 1 FROM voice_vaults WHERE user_id = ?", (user_id,)
        ).fetchone()
    finally:
        connection.close()
    return row is not None


def _clear_expired_device_session(connection: sqlite3.Connection, now: int) -> None:
    connection.execute(
        """
        DELETE FROM device_session
        WHERE singleton_id = 1
          AND (idle_expires_at <= ? OR absolute_expires_at <= ?)
        """,
        (now, now),
    )


def create_account_and_session(
    user_id: str,
    password_hash: str,
    password_salt: str,
    token_hash: str,
    now: int,
    idle_expires_at: int,
    absolute_expires_at: int,
) -> None:
    initialize_database()
    connection = sqlite3.connect(_database_path())
    try:
        connection.execute("BEGIN IMMEDIATE")
        _clear_expired_device_session(connection, now)
        active = connection.execute(
            "SELECT user_id FROM device_session WHERE singleton_id = 1"
        ).fetchone()
        if active is not None:
            raise ActiveUserConflictError(
                "The current user must log out before another account can sign up."
            )
        try:
            connection.execute(
                """
                INSERT INTO accounts(user_id, password_hash, password_salt, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, password_hash, password_salt, now),
            )
        except sqlite3.IntegrityError as exc:
            raise AccountAlreadyExistsError("That user ID already exists.") from exc
        connection.execute(
            """
            INSERT INTO device_session(
                singleton_id, user_id, token_hash, created_at, last_seen_at,
                idle_expires_at, absolute_expires_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                token_hash,
                now,
                now,
                idle_expires_at,
                absolute_expires_at,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_account_credentials(user_id: str) -> tuple[str, str] | None:
    initialize_database()
    connection = sqlite3.connect(_database_path())
    try:
        row = connection.execute(
            "SELECT password_hash, password_salt FROM accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        return None
    return str(row[0]), str(row[1])


def start_device_session(
    user_id: str,
    token_hash: str,
    now: int,
    idle_expires_at: int,
    absolute_expires_at: int,
) -> None:
    initialize_database()
    connection = sqlite3.connect(_database_path())
    try:
        connection.execute("BEGIN IMMEDIATE")
        _clear_expired_device_session(connection, now)
        active = connection.execute(
            "SELECT user_id FROM device_session WHERE singleton_id = 1"
        ).fetchone()
        if active is not None and str(active[0]) != user_id:
            raise ActiveUserConflictError(
                "The current user must log out before another user can log in."
            )
        connection.execute(
            """
            INSERT INTO device_session(
                singleton_id, user_id, token_hash, created_at, last_seen_at,
                idle_expires_at, absolute_expires_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(singleton_id) DO UPDATE SET
                user_id = excluded.user_id,
                token_hash = excluded.token_hash,
                created_at = excluded.created_at,
                last_seen_at = excluded.last_seen_at,
                idle_expires_at = excluded.idle_expires_at,
                absolute_expires_at = excluded.absolute_expires_at
            """,
            (
                user_id,
                token_hash,
                now,
                now,
                idle_expires_at,
                absolute_expires_at,
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def resolve_device_session(
    token_hash: str,
    now: int,
    *,
    idle_ttl_seconds: int,
    touch: bool = True,
) -> dict[str, int | str] | None:
    initialize_database()
    connection = sqlite3.connect(_database_path())
    try:
        connection.execute("BEGIN IMMEDIATE")
        _clear_expired_device_session(connection, now)
        row = connection.execute(
            """
            SELECT user_id, created_at, last_seen_at, idle_expires_at,
                   absolute_expires_at
            FROM device_session
            WHERE singleton_id = 1 AND token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        user_id, created_at, last_seen_at, idle_expires_at, absolute_expires_at = row
        if touch:
            idle_expires_at = min(now + idle_ttl_seconds, int(absolute_expires_at))
            connection.execute(
                """
                UPDATE device_session
                SET last_seen_at = ?, idle_expires_at = ?
                WHERE singleton_id = 1 AND token_hash = ?
                """,
                (now, idle_expires_at, token_hash),
            )
        connection.commit()
        return {
            "user_id": str(user_id),
            "created_at": int(created_at),
            "last_seen_at": now if touch else int(last_seen_at),
            "idle_expires_at": int(idle_expires_at),
            "absolute_expires_at": int(absolute_expires_at),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def end_device_session(token_hash: str) -> None:
    initialize_database()
    connection = sqlite3.connect(_database_path())
    try:
        connection.execute(
            "DELETE FROM device_session WHERE singleton_id = 1 AND token_hash = ?",
            (token_hash,),
        )
        connection.commit()
    finally:
        connection.close()
