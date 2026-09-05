"""Fuzzy-vault prototype shared by the CHAABI DSP and crypto modules."""

from __future__ import annotations

import base64
import hashlib
import itertools
import os
import secrets
from typing import Any, Iterable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from reedsolo import RSCodec, ReedSolomonError


BIN_SIZE = 25
BIN_TOLERANCE = 1
CHAFF_COUNT = 200
RS_PARITY = 8
PBKDF2_ITERATIONS = 310_000
AES_KEY_SIZE = 32
AES_NONCE_SIZE = 12
FIELD_PRIME = 2_147_483_647
MAX_INTERPOLATION_ATTEMPTS = 2_000


class VaultAuthenticationError(Exception):
    """Raised when supplied biometric features cannot unlock a vault."""


def formant_values_from_dsp(dsp_result: dict[str, Any]) -> list[float]:
    """Flatten all valid F1/F2/F3 values from the agreed DSP frame contract."""
    frames = dsp_result.get("formant_frames")
    if not isinstance(frames, list):
        raise ValueError("DSP result must contain a formant_frames list.")

    values: list[float] = []
    for frame in frames:
        if not isinstance(frame, dict):
            continue
        for key in ("f1_hz", "f2_hz", "f3_hz"):
            value = frame.get(key)
            if isinstance(value, (int, float)) and value > 0:
                values.append(float(value))
    return values


def _bin_formant(formant: float) -> int:
    if formant <= 0:
        raise ValueError("Formant must be positive.")
    return int(round(float(formant) / BIN_SIZE))


def _bin_formants(formants: Iterable[float]) -> list[int]:
    bins = sorted({_bin_formant(value) for value in formants if float(value) > 0})
    if not bins:
        raise VaultAuthenticationError("No valid formants.")
    return bins


def count_distinct_formant_bins(formants: Iterable[float]) -> int:
    """Return the number of unique 25 Hz feature bins."""
    return len(_bin_formants(formants))


def _polynomial_value(coefficients: list[int], x: int) -> int:
    result = 0
    for coefficient in reversed(coefficients):
        result = (result * x + coefficient) % FIELD_PRIME
    return result


def _mod_inverse(value: int) -> int:
    value %= FIELD_PRIME
    if value == 0:
        raise ValueError("Cannot invert zero.")
    return pow(value, FIELD_PRIME - 2, FIELD_PRIME)


def _interpolate(points: list[tuple[int, int]]) -> list[int]:
    if not points:
        raise ValueError("No points supplied.")
    if len({x for x, _ in points}) != len(points):
        raise ValueError("Duplicate x coordinates.")

    coefficients = [0] * len(points)
    for index, (x_value, y_value) in enumerate(points):
        basis = [1]
        denominator = 1
        for other_index, (other_x, _) in enumerate(points):
            if index == other_index:
                continue
            denominator = denominator * (x_value - other_x) % FIELD_PRIME
            next_basis = [0] * (len(basis) + 1)
            for power, value in enumerate(basis):
                next_basis[power] = (next_basis[power] - value * other_x) % FIELD_PRIME
                next_basis[power + 1] = (next_basis[power + 1] + value) % FIELD_PRIME
            basis = next_basis

        scale = y_value * _mod_inverse(denominator) % FIELD_PRIME
        for power, value in enumerate(basis):
            coefficients[power] = (coefficients[power] + scale * value) % FIELD_PRIME
    return coefficients


def _derive_key(secret_material: bytes, salt: bytes) -> bytes:
    return PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=AES_KEY_SIZE,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    ).derive(secret_material)


def _decode_secret(encoded: bytes, parity: int) -> bytes:
    try:
        result = RSCodec(parity).decode(encoded)
    except ReedSolomonError as exc:
        raise VaultAuthenticationError("Reed-Solomon authentication failed.") from exc
    return bytes(result[0] if isinstance(result, tuple) else result)


def generate_vault(baseline_formants: Iterable[float]) -> dict[str, Any]:
    """Create a vault using enough distinct bins for every RS symbol."""
    bins = _bin_formants(baseline_formants)
    secret = os.environ.get("CHABI_SECRET", "CHABI-DEMO").encode("utf-8")
    encoded = bytes(RSCodec(RS_PARITY).encode(secret))
    coefficient_count = len(encoded)

    if len(bins) < coefficient_count:
        raise ValueError(
            f"Need at least {coefficient_count} distinct {BIN_SIZE} Hz formant bins, "
            f"but only {len(bins)} were supplied."
        )

    genuine_bins = bins[:coefficient_count]
    coefficients = list(encoded)
    genuine_points = [
        {"x": x_value, "y": _polynomial_value(coefficients, x_value)}
        for x_value in genuine_bins
    ]

    used_x = set(genuine_bins)
    chaff_points: list[dict[str, int]] = []
    while len(chaff_points) < CHAFF_COUNT:
        x_value = secrets.randbelow(FIELD_PRIME - 1) + 1
        if x_value in used_x:
            continue
        y_value = secrets.randbelow(FIELD_PRIME - 1) + 1
        if y_value == _polynomial_value(coefficients, x_value):
            continue
        used_x.add(x_value)
        chaff_points.append({"x": x_value, "y": y_value})

    points = genuine_points + chaff_points
    secrets.SystemRandom().shuffle(points)
    salt = os.urandom(16)
    key = _derive_key(encoded, salt)
    nonce = os.urandom(AES_NONCE_SIZE)
    ciphertext = AESGCM(key).encrypt(nonce, secret, None)

    return {
        "version": 2,
        "bin_size": BIN_SIZE,
        "bin_tolerance": BIN_TOLERANCE,
        "rs_parity": RS_PARITY,
        "coefficient_count": coefficient_count,
        "points": points,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "commitment": hashlib.sha256(encoded).hexdigest(),
    }


def _find_matching_points(
    live_bins: list[int],
    vault_points: list[dict[str, int]],
    tolerance: int,
) -> list[tuple[int, int]]:
    matches: dict[int, int] = {}
    for live_x in live_bins:
        nearby = [
            point
            for point in vault_points
            if abs(int(point["x"]) - live_x) <= tolerance
        ]
        if not nearby:
            continue
        best = min(nearby, key=lambda point: abs(int(point["x"]) - live_x))
        matches[int(best["x"])] = int(best["y"])
    return sorted(matches.items())


def _recover_encoded(
    candidates: list[tuple[int, int]],
    coefficient_count: int,
    commitment: str,
) -> bytes:
    if len(candidates) < coefficient_count:
        raise VaultAuthenticationError(
            f"Need {coefficient_count} matching genuine points, "
            f"but found {len(candidates)}."
        )

    attempts = 0
    for points in itertools.combinations(candidates, coefficient_count):
        attempts += 1
        if attempts > MAX_INTERPOLATION_ATTEMPTS:
            break
        coefficients = _interpolate(list(points))
        if any(coefficient > 255 for coefficient in coefficients):
            continue
        encoded = bytes(coefficients)
        if hashlib.sha256(encoded).hexdigest() == commitment:
            return encoded
    raise VaultAuthenticationError("Voice does not match vault.")


def unlock_vault(live_formants: Iterable[float], vault_data: dict[str, Any]) -> bytes:
    """Recover and decrypt a vault using live formant measurements."""
    try:
        required = {
            "points",
            "salt",
            "nonce",
            "ciphertext",
            "commitment",
            "coefficient_count",
            "rs_parity",
        }
        if not isinstance(vault_data, dict) or not required.issubset(vault_data):
            raise VaultAuthenticationError("Incomplete or invalid vault.")

        coefficient_count = int(vault_data["coefficient_count"])
        if coefficient_count <= 0 or coefficient_count > 255:
            raise VaultAuthenticationError("Invalid coefficient count.")
        tolerance = int(vault_data.get("bin_tolerance", BIN_TOLERANCE))
        live_bins = _bin_formants(live_formants)
        candidates = _find_matching_points(live_bins, vault_data["points"], tolerance)
        encoded = _recover_encoded(
            candidates,
            coefficient_count,
            str(vault_data["commitment"]),
        )
        secret = _decode_secret(encoded, int(vault_data["rs_parity"]))
        salt = base64.b64decode(vault_data["salt"])
        key = _derive_key(encoded, salt)
        plaintext = AESGCM(key).decrypt(
            base64.b64decode(vault_data["nonce"]),
            base64.b64decode(vault_data["ciphertext"]),
            None,
        )
        if plaintext != secret:
            raise VaultAuthenticationError("Recovered payload failed integrity check.")
        return plaintext
    except VaultAuthenticationError:
        raise
    except Exception as exc:
        raise VaultAuthenticationError("Voice authentication failed.") from exc
