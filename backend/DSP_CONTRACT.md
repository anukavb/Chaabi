# DSP Engine Integration Contract

This is the public response contract agreed with the backend teammate. The DSP
engine may calculate additional values internally, but it returns only the
fields documented here.

## Import and call

```python
from dsp_engine import AudioProcessingError, process_audio_buffer

result = process_audio_buffer(
    audio_bytes,
    content_type="audio/wav",
    sample_rate=None,
)
```

Supported formats:

- WAV: `audio/wav`, `audio/x-wav`, or `audio/wave`
- Headerless signed 16-bit little-endian PCM: `audio/pcm`, `audio/l16`, or
  `application/octet-stream`

For raw PCM, `sample_rate` is required. WAV input obtains it from the header.

## Exact success shape

```json
{
  "formant_frames": [
    {
      "frame_id": 1,
      "f1_hz": 500.37,
      "f2_hz": 1499.6,
      "f3_hz": 2501.02,
      "confidence": 0.96
    }
  ],
  "formant_summary": {
    "f1_hz": 500.8,
    "f2_hz": 1499.6,
    "f3_hz": 2500.7
  },
  "liveness_score": 1.0,
  "is_replay_attack": false,
  "liveness_available": true,
  "audio_quality": {
    "sample_rate": 48000,
    "duration_ms": 500.0,
    "speech_detected": true,
    "clipping_detected": false,
    "peak": 0.3773,
    "rms": 0.2338
  },
  "features": {
    "high_frequency_energy_ratio": 0.0
  },
  "reason_codes": []
}
```

## Field meanings

- `formant_frames`: every valid analyzed frame. `frame_id` refers to its
  position in the original 25 ms frame sequence.
- `confidence`: acoustic quality estimate for that frame, from `0.0` to `1.0`.
- `formant_summary`: median F1, F2, and F3 across valid frames.
- `liveness_score`: `1.0` means low measured replay risk; `0.0` means high
  measured replay risk.
- `is_replay_attack`: provisional threshold decision.
- `liveness_available`: whether sufficient speech and frequency range were
  available for liveness analysis.
- `reason_codes`: machine-readable explanations for unavailable or risky input.

If no reliable formants are available, `formant_frames` is empty and summary
values are `null`.

## Low sample-rate behavior

A 16 kHz recording cannot contain frequencies above 16 kHz. It therefore
returns `liveness_available: false`, `liveness_score: null`, and
`high_frequency_energy_ratio: null`. The backend must not treat
`is_replay_attack: false` as proof of liveness in this case.

## Errors

Invalid input raises `AudioProcessingError`, a subclass of `ValueError`.

```python
try:
    dsp_result = process_audio_buffer(audio_bytes, upload.content_type)
except AudioProcessingError as error:
    raise HTTPException(status_code=422, detail=str(error)) from error
```

## Threshold configuration

- `CHAABI_HIGH_REPLAY_RISK_THRESHOLD` defaults to `0.55`.
- `CHAABI_MEDIUM_REPLAY_RISK_THRESHOLD` defaults to `0.30`.
- `CHAABI_HIGH_FREQUENCY_REFERENCE_RATIO` defaults to `0.15`.

The current thresholds are provisional. See `CALIBRATION.md` for the future
real-device calibration workflow.

## Test command

From `backend`:

```powershell
python -m unittest discover -s tests -v
```
