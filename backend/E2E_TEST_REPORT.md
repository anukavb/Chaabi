# CHAABI Person 1 End-to-End Test Report

## Execution summary

- Date: 2026-09-05
- Branch: `pranav-dev`
- Command: `python -m unittest discover -s tests -v`
- Result: 32 tests passed, 0 failed, 0 errors
- Python compilation: passed
- Git whitespace validation: passed

The FastAPI test client emitted a Starlette deprecation warning about its
current HTTP client dependency. It did not affect execution or correctness.

## Tested flow

```text
WAV upload
  -> FastAPI endpoint
  -> audio validation
  -> DSP preprocessing
  -> frame-level LPC formants
  -> acoustic liveness gate
  -> distinct 25 Hz formant bins
  -> fuzzy-vault generation
  -> random challenge session
  -> mocked Sarvam transcript and intent result
  -> fuzzy-vault reconstruction
  -> AES-GCM payload recovery
  -> authenticated API response
```

## DSP tests

- 16 kHz, 44.1 kHz, and 48 kHz WAV handling
- Raw signed 16-bit PCM handling
- Stereo-to-mono conversion
- Empty, malformed, and short input rejection
- Silence and low-level audio rejection
- Clipping detection
- Frame-level F1/F2/F3 contract
- Formant summary generation
- Low-rate ultrasonic-analysis refusal
- Clean and replay-like synthetic liveness decisions

## DSP-to-crypto tests

- Six stable frames produce 18 values but may collapse to only three bins
- Variable-length frames can provide at least 18 distinct bins
- `coefficient_count` follows secret length plus RS parity
- Small formant drift remains matchable
- Clearly different formants are rejected
- Synthetic audio passes through the real DSP before vault generation
- The generated vault reconstructs and decrypts successfully

## API end-to-end tests

- Successful enrollment, challenge, and authentication
- One-shot challenge invalidation after successful use
- Insufficient distinct enrollment features
- Replay rejection before calling Sarvam
- Inconclusive liveness at insufficient sample rate
- Intent mismatch
- Sarvam service failure mapped to HTTP 502
- Vault/voice mismatch
- Invalid audio mapped to HTTP 422
- Unknown and expired sessions
- Unknown users

## Not yet validated

- Real human enrollment and authentication recordings
- Phone-speaker replay on the final demo hardware
- Live Sarvam STT and LLM calls with a real API key
- Browser WebM/Opus conversion
- Persistent multi-user vault storage
- Production CORS and security configuration

Automated tests mock Sarvam calls so they use no API quota. The final live test
must be completed when an API key and recordings are available.
