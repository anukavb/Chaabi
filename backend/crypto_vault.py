"""Fuzzy-vault prototype shared by the CHAABI DSP and crypto modules."""

from __future__ import annotations

import base64
import itertools
import os
import secrets
from typing import Any, Iterable

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.exceptions import InvalidTag
from reedsolo import RSCodec, ReedSolomonError


BIN_SIZE = 25
BIN_TOLERANCE = 1
CHAFF_COUNT = 200
RS_PARITY = 8
AES_KEY_SIZE = 32
AES_NONCE_SIZE = 12
SECRET_SIZE = 10
VAULT_AAD = b"CHAABI-VAULT-V3"
FIELD_PRIME = 2_147_483_647
MAX_INTERPOLATION_ATTEMPTS = 2_000


class VaultAuthenticationError(Exception):
    """Raised when supplied biometric features cannot unlock a vault."""


def required_feature_count() -> int:
    """Return the number of genuine points required by current vault settings."""
    return SECRET_SIZE + RS_PARITY


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


def stable_formant_bins_from_dsp(
    dsp_results: Iterable[dict[str, Any]],
    minimum_recordings: int = 2,
) -> list[int]:
    """Find repeatable 25 Hz bins across separate enrollment recordings.

    A bin is retained when a value within the configured tolerance appears in
    at least ``minimum_recordings`` recordings.  Returning bins (rather than
    Hertz values) prevents accidental double quantisation at the vault boundary.
    """
    recording_bins: list[dict[int, float]] = []
    for result in dsp_results:
        confidence_by_bin: dict[int, float] = {}
        for frame in result.get("formant_frames", []):
            confidence = float(frame.get("confidence", 0.0))
            for key in ("f1_hz", "f2_hz", "f3_hz"):
                value = frame.get(key)
                if isinstance(value, (int, float)) and value > 0:
                    feature_bin = _bin_formant(float(value))
                    confidence_by_bin[feature_bin] = max(
                        confidence_by_bin.get(feature_bin, 0.0), confidence
                    )
        if not confidence_by_bin:
            raise ValueError("Every enrollment recording needs valid formant frames.")
        recording_bins.append(confidence_by_bin)
    if not recording_bins:
        raise ValueError("At least one DSP result is required.")
    if minimum_recordings < 1 or minimum_recordings > len(recording_bins):
        raise ValueError("minimum_recordings is outside the recording count.")

    candidates = sorted({value for values in recording_bins for value in values})
    ranked: list[tuple[int, float, int]] = []
    for candidate in candidates:
        support: list[tuple[int, float]] = []
        for values in recording_bins:
            nearby = [value for value in values if abs(value - candidate) <= BIN_TOLERANCE]
            if nearby:
                best = min(nearby, key=lambda value: (abs(value - candidate), -values[value]))
                support.append((best, values[best]))
        if len(support) >= minimum_recordings:
            canonical = int(round(sum(value for value, _ in support) / len(support)))
            mean_confidence = sum(confidence for _, confidence in support) / len(support)
            ranked.append((len(support), mean_confidence, canonical))

    # Prefer bins present in all recordings, while keeping nearby clusters once.
    selected: list[int] = []
    for _, _, candidate in sorted(ranked, key=lambda item: (-item[0], -item[1], item[2])):
        if all(abs(candidate - existing) > BIN_TOLERANCE for existing in selected):
            selected.append(candidate)
    return selected


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
    return HKDF(
        algorithm=hashes.SHA256(),
        length=AES_KEY_SIZE,
        salt=salt,
        info=VAULT_AAD,
    ).derive(secret_material)


def _decode_secret(encoded: bytes, parity: int) -> bytes:
    try:
        result = RSCodec(parity).decode(encoded)
    except ReedSolomonError as exc:
        raise VaultAuthenticationError("Reed-Solomon authentication failed.") from exc
    return bytes(result[0] if isinstance(result, tuple) else result)


def generate_vault_from_bins(
    feature_bins: Iterable[int], payload: bytes | None = None
) -> dict[str, Any]:
    """Create a vault from already-quantised, distinct acoustic features."""
    bins = sorted({int(value) for value in feature_bins if int(value) > 0})
    if not bins:
        raise ValueError("At least one positive feature bin is required.")
    secret = secrets.token_bytes(SECRET_SIZE)
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
    salt = secrets.token_bytes(16)
    key = _derive_key(secret, salt)
    nonce = secrets.token_bytes(AES_NONCE_SIZE)
    protected_payload = payload or os.getenv(
        "CHAABI_PROTECTED_PAYLOAD", "CHAABI_ACCESS_GRANTED"
    ).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, protected_payload, VAULT_AAD)

    return {
        "version": 3,
        "bin_size": BIN_SIZE,
        "bin_tolerance": BIN_TOLERANCE,
        "rs_parity": RS_PARITY,
        "coefficient_count": coefficient_count,
        "points": points,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def generate_vault(baseline_formants: Iterable[float]) -> dict[str, Any]:
    """Compatibility entry point that accepts formant values in Hertz."""
    return generate_vault_from_bins(_bin_formants(baseline_formants))


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


def _recover_payload(
    candidates: list[tuple[int, int]],
    coefficient_count: int,
    parity: int,
    salt: bytes,
    nonce: bytes,
    ciphertext: bytes,
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
        try:
            secret = _decode_secret(encoded, parity)
            if len(secret) != SECRET_SIZE:
                continue
            key = _derive_key(secret, salt)
            return AESGCM(key).decrypt(nonce, ciphertext, VAULT_AAD)
        except (VaultAuthenticationError, InvalidTag):
            continue
    raise VaultAuthenticationError("Voice does not match vault.")


def unlock_vault_with_details(
    live_formants: Iterable[float], vault_data: dict[str, Any]
) -> tuple[bytes, int]:
    """Recover a vault and return its payload and candidate match count."""
    try:
        required = {
            "points",
            "salt",
            "nonce",
            "ciphertext",
            "coefficient_count",
            "rs_parity",
        }
        if not isinstance(vault_data, dict) or not required.issubset(vault_data):
            raise VaultAuthenticationError("Incomplete or invalid vault.")
        if int(vault_data.get("version", 0)) != 3:
            raise VaultAuthenticationError("Unsupported vault version; re-enrollment required.")

        coefficient_count = int(vault_data["coefficient_count"])
        if coefficient_count <= 0 or coefficient_count > 255:
            raise VaultAuthenticationError("Invalid coefficient count.")
        tolerance = int(vault_data.get("bin_tolerance", BIN_TOLERANCE))
        live_bins = _bin_formants(live_formants)
        candidates = _find_matching_points(live_bins, vault_data["points"], tolerance)
        plaintext = _recover_payload(
            candidates,
            coefficient_count,
            int(vault_data["rs_parity"]),
            base64.b64decode(vault_data["salt"]),
            base64.b64decode(vault_data["nonce"]),
            base64.b64decode(vault_data["ciphertext"]),
        )
        return plaintext, len(candidates)
    except VaultAuthenticationError:
        raise
    except Exception as exc:
        raise VaultAuthenticationError("Voice authentication failed.") from exc


def unlock_vault(live_formants: Iterable[float], vault_data: dict[str, Any]) -> bytes:
    """Recover and decrypt a vault using live formant measurements."""
    plaintext, _ = unlock_vault_with_details(live_formants, vault_data)
    return plaintext
