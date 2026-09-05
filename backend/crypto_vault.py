# crypto_vault.py — TEMPORARY placeholder until Person 2 delivers the real file.
# Matches their contract shape exactly so main.py can run end-to-end.

import random


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