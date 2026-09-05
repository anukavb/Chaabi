# Phase 5 Integration and Handoff

## Run the service

From `backend`:

```powershell
python -m uvicorn main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/docs` for the interactive API page.

## API sequence

1. `POST /voice/enroll` with `user_id` and a 48 kHz WAV file.
2. `GET /api/challenge` immediately before authentication.
3. Record the returned prompt.
4. `POST /voice/authenticate` with `user_id`, `session_id`, and the new WAV.

Authentication succeeds only when:

- usable formant frames are present;
- at least the vault's required number of distinct formant bins match;
- liveness analysis is available;
- replay risk is below the rejection threshold;
- Sarvam confirms the challenge transcript;
- the fuzzy vault reconstructs and decrypts successfully.

## Local end-to-end test

```powershell
python -m unittest discover -s tests -v
```

The Sarvam calls are mocked in automated tests. This verifies local orchestration
without spending API quota or requiring credentials. A final live test still
requires `SARVAM_API_KEY` and real enrollment/authentication recordings.

## Current demo limitations

- Vaults and challenges are stored in memory and disappear on server restart.
- CORS is open for hackathon development and must be restricted later.
- WAV and raw PCM are supported; browser WebM/Opus requires conversion.
- Liveness thresholds still require real-device calibration.
- Automated audio is synthetic and does not establish biometric accuracy.
