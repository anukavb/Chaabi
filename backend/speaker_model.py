"""CPU speaker embeddings backed by SpeechBrain ECAPA-TDNN."""

from __future__ import annotations

import os
from pathlib import Path
import threading
from typing import Any

import numpy as np

from dsp_engine import AudioProcessingError, FORMANT_SAMPLE_RATE, _decode_audio, _resample


MODEL_SOURCE = os.getenv(
    "CHAABI_SPEAKER_MODEL_SOURCE", "speechbrain/spkrec-ecapa-voxceleb"
)
MODEL_DIRECTORY = Path(
    os.getenv(
        "CHAABI_SPEAKER_MODEL_DIR",
        str(Path.home() / ".cache" / "chaabi" / "spkrec-ecapa-voxceleb"),
    )
).expanduser()

_model: Any | None = None
_model_lock = threading.Lock()


def _load_model() -> Any:
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model
        try:
            from speechbrain.inference.speaker import SpeakerRecognition
            from speechbrain.utils.fetching import LocalStrategy

            MODEL_DIRECTORY.mkdir(parents=True, exist_ok=True)
            _model = SpeakerRecognition.from_hparams(
                source=MODEL_SOURCE,
                savedir=str(MODEL_DIRECTORY),
                run_opts={"device": "cpu"},
                # COPY_SKIP_CACHE avoids Windows symlink privileges and leaves
                # a self-contained model directory for later offline use.
                local_strategy=LocalStrategy.COPY_SKIP_CACHE,
            )
        except Exception as exc:
            raise AudioProcessingError(
                "The secure speaker model is unavailable. Complete the one-time "
                "model download before enrollment or authentication."
            ) from exc
    return _model


def extract_speaker_embedding(
    audio_bytes: bytes,
    content_type: str | None = "audio/wav",
    sample_rate: int | None = None,
) -> list[float]:
    """Return a normalized 192-value ECAPA speaker embedding.

    This model is trained for speaker recognition and replaces the earlier
    hand-built MFCC summary, whose genuine and impostor score distributions
    overlapped too heavily for an authentication decision.
    """
    try:
        import torch

        decoded_rate, audio = _decode_audio(audio_bytes, content_type, sample_rate)
        voice = _resample(audio, decoded_rate, FORMANT_SAMPLE_RATE).astype(np.float32)
        if voice.size < FORMANT_SAMPLE_RATE:
            raise AudioProcessingError(
                "At least one second of audio is required for speaker comparison."
            )
        peak = float(np.max(np.abs(voice)))
        if peak <= 1e-6:
            raise AudioProcessingError("Speaker audio has no usable energy.")
        waveform = torch.from_numpy(voice / max(peak, 1.0)).unsqueeze(0)
        with torch.inference_mode():
            embedding = _load_model().encode_batch(waveform).squeeze().cpu().numpy()
        vector = np.asarray(embedding, dtype=np.float64).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if vector.size != 192 or not np.all(np.isfinite(vector)) or norm <= 1e-12:
            raise AudioProcessingError("The speaker model returned an invalid embedding.")
        return [round(float(value), 8) for value in vector / norm]
    except AudioProcessingError:
        raise
    except Exception as exc:
        raise AudioProcessingError("Secure speaker embedding extraction failed.") from exc
