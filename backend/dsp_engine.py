# dsp_engine.py — TEMPORARY placeholder until Person 1 delivers the real file.

import random


class AudioProcessingError(ValueError):
    pass


def process_audio_buffer(audio_bytes: bytes, content_type: str = "audio/wav", sample_rate=None) -> dict:
    if not audio_bytes:
        raise AudioProcessingError("empty data")

    return {
        "formants_hz": {"f1": 500.37, "f2": 1499.60, "f3": 2501.02},
        "formant_frames": [
            {"f1": 501.2, "f2": 1498.7, "f3": 2502.1},
            {"f1": 498.9, "f2": 1501.3, "f3": 2499.8},
        ],
        "formant_confidence": 0.95,
        "liveness_score": 0.98,
        "is_replay_attack": False,
        "liveness_available": True,
        "audio_quality": {
            "sample_rate": 48000,
            "duration_ms": 900.0,
            "speech_detected": True,
            "clipping_detected": False,
            "peak": 0.37,
            "rms": 0.23,
        },
        "features": {"high_frequency_energy_ratio": 0.02},
        "reason_codes": [],
    }