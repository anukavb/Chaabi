# crypto_vault.py — TEMPORARY placeholder until Person 2 delivers the real file.
# Matches their contract shape exactly so main.py can run end-to-end.

import random

from __future__ import annotations

import base64
import hashlib
import os
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from reedsolo import RSCodec, ReedSolomonError


# ============================================================
# CONFIG
# ============================================================

BIN_SIZE = 25

CHAFF_COUNT = 200

# 8 parity bytes = up to 4 corrected byte errors.
RS_PARITY = 8

PBKDF2_ITERATIONS = 310_000

AES_KEY_SIZE = 32
AES_NONCE_SIZE = 12

# CHABI-DEMO is 10 bytes.
# + 8 RS parity = 18 polynomial coefficients.
POLYNOMIAL_DEGREE = 17

FIELD_PRIME = 2_147_483_647


# ============================================================
# EXCEPTION
# ============================================================

class VaultAuthenticationError(Exception):
    pass


def generate_vault(dsp_result: dict) -> dict:
    # Real version: 25Hz binning -> Reed-Solomon polynomial + 200 chaff points.
    # This placeholder just stores the enrollment formants directly.
    return {"opaque": True, "enrolled_formants": dsp_result["formants_hz"]}


def unlock_from_dsp_result(dsp_result: dict, vault_data: dict) -> bytes:
    # Real version: bin live formants, filter chaff, recover polynomial,
    # Reed-Solomon decode, PBKDF2 -> AES-256-GCM decrypt.
    # This placeholder just succeeds most of the time so you can test both branches.
    if random.random() < 0.85:
        return b"CHABI-DEMO-SECRET"
    raise VaultAuthenticationError("formant drift exceeded threshold (placeholder)")
# ============================================================
# FORMANT BINNING
# ============================================================

def _bin_formant(formant: int) -> int:
    if formant <= 0:
        raise ValueError("Formant must be positive.")

    return int(round(formant / BIN_SIZE))


def _bin_formants(formants: list[int]) -> list[int]:
    bins = sorted({
        _bin_formant(int(f))
        for f in formants
        if int(f) > 0
    })

    if not bins:
        raise VaultAuthenticationError(
            "No valid formants."
        )

    return bins


# ============================================================
# POLYNOMIAL MATH
# ============================================================

def _polynomial_value(
    coefficients: list[int],
    x: int,
) -> int:

    result = 0

    for coefficient in reversed(coefficients):
        result = (
            result * x + coefficient
        ) % FIELD_PRIME

    return result


def _mod_inverse(value: int) -> int:

    value %= FIELD_PRIME

    if value == 0:
        raise ValueError(
            "Cannot invert zero."
        )

    return pow(
        value,
        FIELD_PRIME - 2,
        FIELD_PRIME,
    )


def _interpolate(
    points: list[tuple[int, int]],
) -> list[int]:

    n = len(points)

    if n == 0:
        raise ValueError(
            "No points supplied."
        )

    xs = [p[0] for p in points]

    if len(set(xs)) != n:
        raise ValueError(
            "Duplicate x coordinates."
        )

    coefficients = [0] * n

    for i in range(n):

        xi, yi = points[i]

        basis = [1]
        denominator = 1

        for j in range(n):

            if i == j:
                continue

            xj = xs[j]

            denominator = (
                denominator *
                (xi - xj)
            ) % FIELD_PRIME

            new_basis = [
                0
            ] * (len(basis) + 1)

            for k, value in enumerate(basis):

                new_basis[k] = (
                    new_basis[k]
                    - value * xj
                ) % FIELD_PRIME

                new_basis[k + 1] = (
                    new_basis[k + 1]
                    + value
                ) % FIELD_PRIME

            basis = new_basis

        scale = (
            yi *
            _mod_inverse(denominator)
        ) % FIELD_PRIME

        for k, value in enumerate(basis):

            coefficients[k] = (
                coefficients[k]
                + scale * value
            ) % FIELD_PRIME

    return coefficients


# ============================================================
# REED-SOLOMON
# ============================================================

def _rs_encode(
    secret: bytes,
) -> bytes:

    codec = RSCodec(RS_PARITY)

    return bytes(
        codec.encode(secret)
    )


def _rs_decode(
    encoded: bytes,
) -> bytes:

    codec = RSCodec(RS_PARITY)

    result = codec.decode(encoded)

    if isinstance(result, tuple):
        return bytes(result[0])

    return bytes(result)


# ============================================================
# PBKDF2
# ============================================================

def _derive_key(
    secret_material: bytes,
    salt: bytes,
) -> bytes:

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=AES_KEY_SIZE,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )

    return kdf.derive(
        secret_material
    )


# ============================================================
# AES-GCM
# ============================================================

def _encrypt(
    key: bytes,
    plaintext: bytes,
) -> tuple[bytes, bytes]:

    nonce = os.urandom(
        AES_NONCE_SIZE
    )

    aes = AESGCM(key)

    ciphertext = aes.encrypt(
        nonce,
        plaintext,
        None,
    )

    return nonce, ciphertext


def _decrypt(
    key: bytes,
    nonce: bytes,
    ciphertext: bytes,
) -> bytes:

    aes = AESGCM(key)

    return aes.decrypt(
        nonce,
        ciphertext,
        None,
    )


# ============================================================
# GENERATE VAULT
# ============================================================

def generate_vault(
    baseline_formants: list[int],
) -> dict:

    bins = _bin_formants(
        baseline_formants
    )

    secret = os.environ.get(
        "CHABI_SECRET",
        "CHABI-DEMO",
    ).encode("utf-8")

    # --------------------------------------------------------
    # Reed-Solomon
    # --------------------------------------------------------

    encoded = _rs_encode(
        secret
    )

    # Each RS symbol is one polynomial coefficient.
    coefficients = list(encoded)

    required_points = len(
        coefficients
    )

    if len(bins) < required_points:

        raise ValueError(
            f"Need at least {required_points} "
            f"distinct 25 Hz formant bins, "
            f"but only {len(bins)} were supplied."
        )

    # --------------------------------------------------------
    # Genuine points
    # --------------------------------------------------------

    genuine_bins = bins[
        :required_points
    ]

    genuine_points = []

    for x in genuine_bins:

        y = _polynomial_value(
            coefficients,
            x,
        )

        genuine_points.append({
            "x": x,
            "y": y,
        })

    # --------------------------------------------------------
    # Chaff
    # --------------------------------------------------------

    used_x = {
        point["x"]
        for point in genuine_points
    }

    chaff_points = []

    while len(chaff_points) < CHAFF_COUNT:

        x = secrets.randbelow(
            FIELD_PRIME - 1
        ) + 1

        if x in used_x:
            continue

        y = secrets.randbelow(
            FIELD_PRIME - 1
        ) + 1

        if y == _polynomial_value(
            coefficients,
            x,
        ):
            continue

        used_x.add(x)

        chaff_points.append({
            "x": x,
            "y": y,
        })

    # --------------------------------------------------------
    # Mix points
    # --------------------------------------------------------

    points = (
        genuine_points +
        chaff_points
    )

    secrets.SystemRandom().shuffle(
        points
    )

    # --------------------------------------------------------
    # AES key
    # --------------------------------------------------------

    salt = os.urandom(16)

    key = _derive_key(
        encoded,
        salt,
    )

    nonce, ciphertext = _encrypt(
        key,
        secret,
    )

    return {
        "version": 1,
        "bin_size": BIN_SIZE,
        "rs_parity": RS_PARITY,
        "points": points,
        "salt": base64.b64encode(
            salt
        ).decode(),
        "nonce": base64.b64encode(
            nonce
        ).decode(),
        "ciphertext": base64.b64encode(
            ciphertext
        ).decode(),
        "commitment": hashlib.sha256(
            encoded
        ).hexdigest(),
    }


# ============================================================
# FIND VOICE-MATCHED POINTS
# ============================================================

def _find_matching_points(
    live_bins: list[int],
    vault_points: list[dict],
) -> list[tuple[int, int]]:

    matches = {}

    for live_x in live_bins:

        best = None
        best_distance = None

        for point in vault_points:

            vault_x = int(
                point["x"]
            )

            distance = abs(
                vault_x - live_x
            )

            # ±1 bin = ±25 Hz
            if distance > 1:
                continue

            if (
                best_distance is None
                or distance < best_distance
            ):
                best = point
                best_distance = distance

        if best is not None:

            x = int(best["x"])
            y = int(best["y"])

            matches[x] = y

    return list(
        matches.items()
    )


# ============================================================
# UNLOCK
# ============================================================

def unlock_vault(
    live_formants: list[int],
    vault_data: dict,
) -> bytes:

    try:

        if not isinstance(
            vault_data,
            dict,
        ):
            raise VaultAuthenticationError(
                "Invalid vault."
            )

        required = {
            "points",
            "salt",
            "nonce",
            "ciphertext",
            "commitment",
        }

        if not required.issubset(
            vault_data
        ):
            raise VaultAuthenticationError(
                "Incomplete vault."
            )

        # ----------------------------------------------------
        # Live voice → bins
        # ----------------------------------------------------

        live_bins = _bin_formants(
            live_formants
        )

        # ----------------------------------------------------
        # Match voice features to vault
        # ----------------------------------------------------

        candidates = _find_matching_points(
            live_bins,
            vault_data["points"],
        )

        rs_parity = int(
            vault_data["rs_parity"]
        )

        required_points = rs_parity

        # The polynomial needs:
        #
        # number of RS bytes
        #
        # For CHABI-DEMO:
        #
        # 10 secret bytes
        # + 8 parity
        # = 18 points

        if len(candidates) < required_points:

            raise VaultAuthenticationError(
                "Not enough matching voice features."
            )

        # ----------------------------------------------------
        # We expect the genuine points to have unique x values.
        #
        # Try subsets until a polynomial is found whose
        # coefficients are all valid RS byte values.
        # ----------------------------------------------------

        # Since genuine points correspond to the first N
        # baseline bins, take the closest candidates first.
        #
        # For the demo this is deterministic and fast.

        candidates = sorted(
            candidates,
            key=lambda p: p[0],
        )

        # We need to discover polynomial degree from the
        # number of RS symbols.
        #
        # The vault itself contains enough information to
        # determine the required number of coefficients from
        # its genuine point count.
        #
        # Infer it by looking at the maximum polynomial
        # requirement encoded in the vault metadata.
        #
        # Current CHABI format stores this implicitly.
        #
        # We use the first 18 matched points for the demo.
        #
        # Later this will become explicit metadata.

        point_count = min(
            len(candidates),
            18,
        )

        if point_count < 18:

            raise VaultAuthenticationError(
                "Insufficient genuine points."
            )

        points = candidates[
            :18
        ]

        coefficients = _interpolate(
            points
        )

        # ----------------------------------------------------
        # Polynomial coefficients must be bytes.
        # ----------------------------------------------------

        if any(
            coefficient < 0
            or coefficient > 255
            for coefficient in coefficients
        ):
            raise VaultAuthenticationError(
                "Recovered polynomial is invalid."
            )

        encoded = bytes(
            coefficients
        )

        # ----------------------------------------------------
        # Commitment check
        # ----------------------------------------------------

        commitment = hashlib.sha256(
            encoded
        ).hexdigest()

        if commitment != vault_data[
            "commitment"
        ]:
            raise VaultAuthenticationError(
                "Voice does not match vault."
            )

        # ----------------------------------------------------
        # Reed-Solomon decode
        # ----------------------------------------------------

        try:

            secret = _rs_decode(
                encoded
            )

        except ReedSolomonError as exc:

            raise VaultAuthenticationError(
                "Reed-Solomon authentication failed."
            ) from exc

        # ----------------------------------------------------
        # Derive AES-256 key
        # ----------------------------------------------------

        salt = base64.b64decode(
            vault_data["salt"]
        )

        key = _derive_key(
            encoded,
            salt,
        )

        # ----------------------------------------------------
        # AES-GCM
        # ----------------------------------------------------

        nonce = base64.b64decode(
            vault_data["nonce"]
        )

        ciphertext = base64.b64decode(
            vault_data["ciphertext"]
        )

        plaintext = _decrypt(
            key,
            nonce,
            ciphertext,
        )

        # ----------------------------------------------------
        # Final integrity check
        # ----------------------------------------------------

        if not plaintext:

            raise VaultAuthenticationError(
                "Empty authenticated payload."
            )

        return plaintext

    except VaultAuthenticationError:
        raise

    except Exception as exc:

        raise VaultAuthenticationError(
            "Voice authentication failed."
        ) from exc


# ============================================================
# MODULE TEST
# ============================================================

if __name__ == "__main__":

    print("CHABI crypto vault loaded.")
