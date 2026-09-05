"""Acoustic feature extraction for the CHAABI prototype.

This module intentionally contains no API, storage, cryptography, or Sarvam AI
code. Its public entry point accepts an in-memory audio buffer and returns a
JSON-serializable diagnostic dictionary for the backend orchestrator.
"""

from __future__ import annotations

from io import BytesIO
from math import gcd
import os
from typing import Any

import numpy as np
from scipy import signal
from scipy.io import wavfile
from scipy.linalg import solve_toeplitz


def _environment_ratio(name: str, default: float) -> float:
    """Read a configurable ratio while failing clearly on unsafe values."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number between 0 and 1.") from exc
    if not 0.0 <= value <= 1.0:
        raise RuntimeError(f"{name} must be between 0 and 1.")
    return value


FORMANT_SAMPLE_RATE = 16_000
PRE_EMPHASIS_ALPHA = 0.97
LPC_ORDER = 18
FRAME_MS = 25
HOP_MS = 10
HIGH_FREQUENCY_REFERENCE_RATIO = _environment_ratio(
    "CHAABI_HIGH_FREQUENCY_REFERENCE_RATIO", 0.15
)
HIGH_REPLAY_RISK_THRESHOLD = _environment_ratio(
    "CHAABI_HIGH_REPLAY_RISK_THRESHOLD", 0.55
)
MEDIUM_REPLAY_RISK_THRESHOLD = _environment_ratio(
    "CHAABI_MEDIUM_REPLAY_RISK_THRESHOLD", 0.30
)
MIN_AUDIO_RMS = 0.003
MAX_CLIPPING_RATIO = 0.01
MIN_FRAME_PERIODICITY = 0.20
MIN_VOICED_FRAMES = 3


class AudioProcessingError(ValueError):
    """Raised when an audio buffer cannot be processed safely."""


def _to_float_mono(samples: np.ndarray) -> np.ndarray:
    """Convert integer or float audio samples to finite mono float64 audio."""
    if samples.ndim == 2:
        samples = samples.astype(np.float64).mean(axis=1)
    elif samples.ndim != 1:
        raise AudioProcessingError("Audio must be mono or stereo.")

    if np.issubdtype(samples.dtype, np.signedinteger):
        info = np.iinfo(samples.dtype)
        scale = float(max(abs(info.min), info.max))
        audio = samples.astype(np.float64) / scale
    elif np.issubdtype(samples.dtype, np.unsignedinteger):
        info = np.iinfo(samples.dtype)
        midpoint = (info.max + 1) / 2.0
        audio = (samples.astype(np.float64) - midpoint) / midpoint
    elif np.issubdtype(samples.dtype, np.floating):
        audio = samples.astype(np.float64)
    else:
        raise AudioProcessingError(f"Unsupported sample type: {samples.dtype}.")

    if not np.all(np.isfinite(audio)):
        raise AudioProcessingError("Audio contains non-finite sample values.")
    return np.clip(audio, -1.0, 1.0)


def _decode_audio(
    audio_bytes: bytes,
    content_type: str | None,
    sample_rate: int | None,
) -> tuple[int, np.ndarray]:
    if not audio_bytes:
        raise AudioProcessingError("Audio buffer is empty.")

    normalized_type = (content_type or "audio/wav").split(";", 1)[0].strip().lower()
    is_wav = normalized_type in {"audio/wav", "audio/x-wav", "audio/wave"}
    is_wav = is_wav or audio_bytes[:4] in {b"RIFF", b"RIFX", b"RF64"}

    if is_wav:
        try:
            decoded_rate, samples = wavfile.read(BytesIO(audio_bytes))
        except Exception as exc:
            raise AudioProcessingError("Audio is not a valid WAV buffer.") from exc
    elif normalized_type in {
        "audio/pcm",
        "audio/l16",
        "application/octet-stream",
    }:
        if sample_rate is None:
            raise AudioProcessingError("sample_rate is required for raw 16-bit PCM.")
        if len(audio_bytes) % 2:
            raise AudioProcessingError("Raw 16-bit PCM must contain complete samples.")
        decoded_rate = sample_rate
        samples = np.frombuffer(audio_bytes, dtype="<i2")
    else:
        raise AudioProcessingError(f"Unsupported audio content type: {normalized_type}.")

    decoded_rate = int(decoded_rate)
    if decoded_rate < 8_000 or decoded_rate > 192_000:
        raise AudioProcessingError(f"Unsupported sample rate: {decoded_rate} Hz.")

    audio = _to_float_mono(np.asarray(samples))
    if audio.size / decoded_rate < 0.10:
        raise AudioProcessingError("Audio must be at least 100 ms long.")
    return decoded_rate, audio


def _resample(audio: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return audio.copy()
    common = gcd(source_rate, target_rate)
    return signal.resample_poly(audio, target_rate // common, source_rate // common)


def _preprocess_formant_path(audio: np.ndarray, source_rate: int) -> np.ndarray:
    voice = _resample(audio, source_rate, FORMANT_SAMPLE_RATE)
    voice = voice - float(np.mean(voice))
    voice = signal.lfilter([1.0, -PRE_EMPHASIS_ALPHA], [1.0], voice)
    sos = signal.butter(
        4,
        [300, 3_400],
        btype="bandpass",
        fs=FORMANT_SAMPLE_RATE,
        output="sos",
    )
    return signal.sosfilt(sos, voice)


def _frame_audio(audio: np.ndarray) -> list[np.ndarray]:
    frame_size = FORMANT_SAMPLE_RATE * FRAME_MS // 1_000
    hop_size = FORMANT_SAMPLE_RATE * HOP_MS // 1_000
    if audio.size < frame_size:
        return []
    return [
        audio[start : start + frame_size]
        for start in range(0, audio.size - frame_size + 1, hop_size)
    ]


def _frame_periodicity(frame: np.ndarray) -> float:
    """Estimate whether a frame has the repeating structure of voiced speech."""
    centered = frame - float(np.mean(frame))
    energy = float(np.dot(centered, centered))
    if energy <= 1e-12:
        return 0.0

    autocorrelation = signal.correlate(centered, centered, mode="full", method="fft")
    autocorrelation = autocorrelation[centered.size - 1 :]
    minimum_lag = FORMANT_SAMPLE_RATE // 400
    maximum_lag = min(FORMANT_SAMPLE_RATE // 60, autocorrelation.size - 1)
    if maximum_lag <= minimum_lag:
        return 0.0
    return float(
        np.clip(
            np.max(autocorrelation[minimum_lag : maximum_lag + 1]) / energy,
            0.0,
            1.0,
        )
    )


def _formants_from_frame(frame: np.ndarray) -> tuple[float, float, float] | None:
    windowed = frame * np.hamming(frame.size)
    autocorrelation = np.correlate(windowed, windowed, mode="full")[frame.size - 1 :]
    if autocorrelation[0] <= 1e-10:
        return None

    try:
        coefficients = solve_toeplitz(
            autocorrelation[:LPC_ORDER],
            -autocorrelation[1 : LPC_ORDER + 1],
            check_finite=False,
        )
    except (ValueError, np.linalg.LinAlgError):
        return None

    roots = np.roots(np.concatenate(([1.0], coefficients)))
    roots = roots[np.imag(roots) > 0.0]
    if roots.size == 0:
        return None

    frequencies = np.angle(roots) * FORMANT_SAMPLE_RATE / (2.0 * np.pi)
    magnitudes = np.maximum(np.abs(roots), 1e-12)
    bandwidths = -FORMANT_SAMPLE_RATE * np.log(magnitudes) / np.pi
    candidates = sorted(
        float(frequency)
        for frequency, bandwidth in zip(frequencies, bandwidths)
        if 90.0 < frequency < 5_000.0 and 0.0 < bandwidth < 700.0
    )
    if len(candidates) < 3:
        return None

    f1_candidates = [value for value in candidates if 150.0 <= value <= 1_200.0]
    if not f1_candidates:
        return None
    f1 = f1_candidates[0]

    f2_candidates = [
        value for value in candidates if 500.0 <= value <= 3_500.0 and value >= f1 + 200.0
    ]
    if not f2_candidates:
        return None
    f2 = f2_candidates[0]

    f3_candidates = [
        value for value in candidates if 1_200.0 <= value <= 4_500.0 and value >= f2 + 300.0
    ]
    if not f3_candidates:
        return None
    f3 = f3_candidates[0]
    return f1, f2, f3


def _extract_formants(
    audio: np.ndarray,
) -> tuple[
    list[dict[str, float | int]],
    dict[str, float | None],
    float,
    bool,
]:
    frames = _frame_audio(audio)
    empty_summary = {"f1_hz": None, "f2_hz": None, "f3_hz": None}
    if not frames:
        return [], empty_summary, 0.0, False

    energies = np.asarray([np.sqrt(np.mean(frame * frame)) for frame in frames])
    periodicities = np.asarray([_frame_periodicity(frame) for frame in frames])
    energy_floor = max(MIN_AUDIO_RMS, float(np.percentile(energies, 60)) * 0.20)
    voiced_entries = [
        (frame_index, frame, float(energy), float(periodicity))
        for frame_index, (frame, energy, periodicity) in enumerate(
            zip(frames, energies, periodicities),
            start=1,
        )
        if energy >= energy_floor and periodicity >= MIN_FRAME_PERIODICITY
    ]
    minimum_required = min(MIN_VOICED_FRAMES, len(frames))
    speech_detected = len(voiced_entries) >= minimum_required
    if not speech_detected:
        return [], empty_summary, 0.0, False

    measurements: list[tuple[int, tuple[float, float, float], float]] = []
    for frame_id, frame, energy, periodicity in voiced_entries:
        formants = _formants_from_frame(frame)
        if formants is None:
            continue
        energy_confidence = float(np.clip(energy / (2.0 * energy_floor), 0.0, 1.0))
        frame_confidence = float(
            np.clip(0.70 * periodicity + 0.30 * energy_confidence, 0.0, 1.0)
        )
        measurements.append((frame_id, formants, frame_confidence))

    if not measurements:
        return [], empty_summary, 0.0, True

    values = np.asarray([formants for _, formants, _ in measurements])
    medians = np.median(values, axis=0)
    valid_ratio = len(measurements) / max(len(voiced_entries), 1)
    spread = np.median(np.abs(values - medians), axis=0)
    relative_spread = float(np.mean(spread / np.maximum(medians, 1.0)))
    stability = float(np.clip(1.0 - relative_spread / 0.15, 0.0, 1.0))
    frame_support = float(np.clip(len(measurements) / 5.0, 0.0, 1.0))
    confidence = float(np.clip(valid_ratio * stability * frame_support, 0.0, 1.0))

    formant_frames = [
        {
            "frame_id": frame_id,
            "f1_hz": round(float(formants[0]), 2),
            "f2_hz": round(float(formants[1]), 2),
            "f3_hz": round(float(formants[2]), 2),
            "confidence": round(frame_confidence, 3),
        }
        for frame_id, formants, frame_confidence in measurements
    ]
    return (
        formant_frames,
        {
            "f1_hz": round(float(medians[0]), 2),
            "f2_hz": round(float(medians[1]), 2),
            "f3_hz": round(float(medians[2]), 2),
        },
        round(confidence, 3),
        True,
    )


def _spectral_features(audio: np.ndarray, sample_rate: int) -> dict[str, float | None]:
    """Return raw spectral measurements used by the replay-risk heuristic."""
    centered = audio - float(np.mean(audio))
    spectrum = np.fft.rfft(centered * np.hanning(centered.size))
    power = np.abs(spectrum) ** 2
    frequencies = np.fft.rfftfreq(centered.size, d=1.0 / sample_rate)
    usable_mask = frequencies >= 20.0
    usable_power = power[usable_mask]
    usable_frequencies = frequencies[usable_mask]
    usable = usable_power.sum()
    if usable <= 1e-20:
        return {
            "high_frequency_energy_ratio": (0.0 if sample_rate > 32_000 else None),
            "spectral_flatness": 0.0,
            "spectral_rolloff_hz": 0.0,
            "spectral_rolloff_ratio": 0.0,
        }

    epsilon = max(float(np.mean(usable_power)) * 1e-12, 1e-30)
    flatness = float(
        np.exp(np.mean(np.log(usable_power + epsilon)))
        / (np.mean(usable_power) + epsilon)
    )
    cumulative_power = np.cumsum(usable_power)
    rolloff_index = min(
        int(np.searchsorted(cumulative_power, 0.95 * cumulative_power[-1])),
        usable_frequencies.size - 1,
    )
    rolloff_hz = float(usable_frequencies[rolloff_index])
    nyquist = sample_rate / 2.0
    high_frequency_ratio = (
        float(power[frequencies > 16_000.0].sum() / usable)
        if sample_rate > 32_000
        else None
    )
    return {
        "high_frequency_energy_ratio": high_frequency_ratio,
        "spectral_flatness": flatness,
        "spectral_rolloff_hz": rolloff_hz,
        "spectral_rolloff_ratio": rolloff_hz / nyquist,
    }


def _score_replay_risk(
    features: dict[str, float | None],
    clipping_ratio: float,
) -> tuple[float, str, dict[str, float], list[str]]:
    """Combine explainable, provisional features into a replay-risk score."""
    high_frequency_ratio = features["high_frequency_energy_ratio"]
    if high_frequency_ratio is None:
        raise ValueError("High-frequency analysis is unavailable.")

    flatness = float(features["spectral_flatness"] or 0.0)
    rolloff_ratio = float(features["spectral_rolloff_ratio"] or 0.0)
    components = {
        "high_frequency": float(
            np.clip(high_frequency_ratio / HIGH_FREQUENCY_REFERENCE_RATIO, 0.0, 1.0)
        ),
        "spectral_flatness": float(np.clip((flatness - 0.10) / 0.50, 0.0, 1.0)),
        "spectral_rolloff": float(
            np.clip((rolloff_ratio - 0.55) / 0.40, 0.0, 1.0)
        ),
        "clipping": float(np.clip(clipping_ratio / 0.05, 0.0, 1.0)),
    }
    risk = float(
        0.60 * components["high_frequency"]
        + 0.15 * components["spectral_flatness"]
        + 0.15 * components["spectral_rolloff"]
        + 0.10 * components["clipping"]
    )

    reasons: list[str] = []
    if high_frequency_ratio >= HIGH_FREQUENCY_REFERENCE_RATIO * 0.5:
        reasons.append("ELEVATED_HIGH_FREQUENCY_ENERGY")
    if flatness >= 0.35:
        reasons.append("HIGH_SPECTRAL_FLATNESS")
    if rolloff_ratio >= 0.80:
        reasons.append("HIGH_SPECTRAL_ROLLOFF")

    if risk >= HIGH_REPLAY_RISK_THRESHOLD:
        level = "high"
    elif risk >= MEDIUM_REPLAY_RISK_THRESHOLD:
        level = "medium"
    else:
        level = "low"
    return risk, level, components, reasons


def process_audio_buffer(
    audio_bytes: bytes,
    content_type: str | None = "audio/wav",
    sample_rate: int | None = None,
) -> dict[str, Any]:
    """Extract formants and initial liveness diagnostics from in-memory audio."""
    decoded_rate, audio = _decode_audio(audio_bytes, content_type, sample_rate)
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio * audio)))
    clipping_ratio = float(np.mean(np.abs(audio) >= 0.99))

    formant_audio = _preprocess_formant_path(audio, decoded_rate)
    formant_frames, formant_summary, confidence, speech_detected = _extract_formants(
        formant_audio
    )
    spectral_features = _spectral_features(audio, decoded_rate)
    high_frequency_ratio = spectral_features["high_frequency_energy_ratio"]
    clipping_detected = clipping_ratio > MAX_CLIPPING_RATIO
    if clipping_detected:
        confidence = round(confidence * 0.5, 3)
        for frame in formant_frames:
            frame["confidence"] = round(float(frame["confidence"]) * 0.5, 3)

    reason_codes: list[str] = []
    if rms < MIN_AUDIO_RMS:
        reason_codes.append("LOW_AUDIO_LEVEL")
    if not speech_detected:
        reason_codes.append("NO_SPEECH_DETECTED")
        reason_codes.append("INSUFFICIENT_VOICED_FRAMES")
    if formant_summary["f1_hz"] is None:
        reason_codes.append("FORMANTS_UNAVAILABLE")
    elif confidence < 0.35:
        reason_codes.append("UNSTABLE_FORMANTS")
    if clipping_detected:
        reason_codes.append("EXCESSIVE_CLIPPING")
    if high_frequency_ratio is None:
        reason_codes.append("ULTRASONIC_ANALYSIS_UNAVAILABLE")

    liveness_available = high_frequency_ratio is not None and speech_detected
    replay_risk_score: float | None = None
    if liveness_available:
        risk, _, _, replay_reasons = _score_replay_risk(
            spectral_features,
            clipping_ratio,
        )
        replay_risk_score = round(risk, 3)
        reason_codes.extend(replay_reasons)

    is_replay = bool(
        replay_risk_score is not None
        and replay_risk_score >= HIGH_REPLAY_RISK_THRESHOLD
    )
    if is_replay:
        reason_codes.append("HIGH_REPLAY_RISK")

    if replay_risk_score is None:
        liveness_score = None
    else:
        liveness_score = round(1.0 - replay_risk_score, 3)

    return {
        "formant_frames": formant_frames,
        "formant_summary": formant_summary,
        "liveness_score": liveness_score,
        "is_replay_attack": is_replay,
        "liveness_available": liveness_available,
        "audio_quality": {
            "sample_rate": decoded_rate,
            "duration_ms": round(audio.size * 1_000.0 / decoded_rate, 1),
            "speech_detected": speech_detected,
            "clipping_detected": clipping_detected,
            "peak": round(peak, 4),
            "rms": round(rms, 4),
        },
        "features": {
            "high_frequency_energy_ratio": (
                None if high_frequency_ratio is None else round(high_frequency_ratio, 6)
            )
        },
        "reason_codes": reason_codes,
    }
