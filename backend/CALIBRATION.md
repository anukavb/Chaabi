# DSP Calibration Guide

Phase 4 calibration does not train the engine on user identities. It measures
how well the current replay-risk score separates live and replayed speech on the
devices used for the demonstration.

The project can run before recordings are available. Until this procedure is
completed, all thresholds must be described as provisional.

## Prepare recordings later

Keep private recordings outside the repository. Create this structure anywhere
on the local computer:

```text
chaabi-calibration-audio/
|-- live/
|   |-- sample-01.wav
|   `-- sample-02.wav
`-- replay/
    |-- sample-01.wav
    `-- sample-02.wav
```

Recommended minimum:

- 3-5 consenting speakers;
- 2 live recordings per speaker;
- 2 phone-speaker replay recordings per speaker;
- 48 kHz WAV where possible;
- the microphone and playback device intended for the demo.

The words may vary because this calibration targets acoustics, not transcript
accuracy. Use normal spoken phrases of approximately 3-5 seconds.

## Run calibration

From the `backend` directory:

```powershell
python calibrate_dsp.py "C:\path\to\chaabi-calibration-audio"
```

To choose a specific results location:

```powershell
python calibrate_dsp.py "C:\path\to\chaabi-calibration-audio" --output "C:\path\to\dsp_measurements.csv"
```

The CSV contains derived measurements only. It does not contain audio bytes or
transcripts and uses anonymous trial identifiers instead of filenames.

## Apply a recommended threshold

Set the recommended value before starting FastAPI:

```powershell
$env:CHAABI_HIGH_REPLAY_RISK_THRESHOLD = "0.55"
python main.py
```

Optional settings:

```powershell
$env:CHAABI_MEDIUM_REPLAY_RISK_THRESHOLD = "0.30"
$env:CHAABI_HIGH_FREQUENCY_REFERENCE_RATIO = "0.15"
```

Do not change the high-frequency reference ratio from a small dataset without
reviewing the raw measurement distributions.

## Interpretation

- The recommended threshold maximizes observed accuracy on the supplied trials.
- This observed accuracy is not a guarantee for every user or device.
- Inconclusive recordings are excluded from the recommendation.
- Both live and replay samples are required for a recommendation.
- Record false accepts and false rejects honestly during the final demo test.

## Privacy and repository rules

- Never commit personal voice recordings.
- Obtain consent from every recorded participant.
- Keep only anonymous derived metrics when sharing results.
- Do not describe the calibration set as biometric enrollment data.
