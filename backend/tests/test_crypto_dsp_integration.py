"""Joint tests for the variable-length DSP-to-crypto feature contract."""

from io import BytesIO
import os
import unittest
from unittest.mock import patch

import numpy as np
from scipy.io import wavfile

from crypto_vault import (
    VaultAuthenticationError,
    count_distinct_formant_bins,
    formant_values_from_dsp,
    generate_vault,
    unlock_vault,
)
from dsp_engine import process_audio_buffer


def dsp_frames_with_distinct_bins() -> dict:
    frames = []
    for frame_id in range(1, 9):
        frames.append(
            {
                "frame_id": frame_id,
                "f1_hz": 300 + frame_id * 75,
                "f2_hz": 1_100 + frame_id * 100,
                "f3_hz": 2_300 + frame_id * 125,
                "confidence": 0.9,
            }
        )
    return {"formant_frames": frames}


def diverse_voice_like_wav() -> bytes:
    sample_rate = 48_000
    formant_sets = [
        (350, 1_100, 2_250),
        (475, 1_275, 2_475),
        (600, 1_450, 2_700),
        (725, 1_625, 2_925),
        (850, 1_800, 3_150),
        (975, 1_975, 3_350),
        (425, 1_175, 2_350),
        (550, 1_350, 2_575),
        (675, 1_525, 2_800),
        (800, 1_700, 3_025),
    ]
    time = np.arange(int(sample_rate * 0.16)) / sample_rate
    segments = [
        0.24 * np.sin(2 * np.pi * f1 * time)
        + 0.18 * np.sin(2 * np.pi * f2 * time)
        + 0.12 * np.sin(2 * np.pi * f3 * time)
        for f1, f2, f3 in formant_sets
    ]
    output = BytesIO()
    wavfile.write(
        output,
        sample_rate,
        np.int16(np.clip(np.concatenate(segments), -1.0, 1.0) * 32_767),
    )
    return output.getvalue()


class CryptoDspIntegrationTests(unittest.TestCase):
    def test_six_stable_frames_do_not_imply_eighteen_distinct_bins(self) -> None:
        dsp_result = {
            "formant_frames": [
                {
                    "frame_id": frame_id,
                    "f1_hz": 500 + frame_id,
                    "f2_hz": 1_500 + frame_id,
                    "f3_hz": 2_500 + frame_id,
                    "confidence": 0.95,
                }
                for frame_id in range(1, 7)
            ]
        }
        values = formant_values_from_dsp(dsp_result)

        self.assertEqual(len(values), 18)
        self.assertEqual(count_distinct_formant_bins(values), 3)
        with self.assertRaisesRegex(ValueError, "18 distinct"):
            generate_vault(values)

    def test_variable_frames_can_generate_and_unlock_vault(self) -> None:
        values = formant_values_from_dsp(dsp_frames_with_distinct_bins())

        self.assertGreaterEqual(count_distinct_formant_bins(values), 18)
        with patch.dict(os.environ, {"CHABI_SECRET": "CHABI-DEMO"}):
            vault = generate_vault(values)
            plaintext = unlock_vault(values, vault)

        self.assertEqual(vault["coefficient_count"], 18)
        self.assertEqual(plaintext, b"CHABI-DEMO")

    def test_coefficient_count_tracks_secret_length(self) -> None:
        values = formant_values_from_dsp(dsp_frames_with_distinct_bins())

        with patch.dict(os.environ, {"CHABI_SECRET": "SHORT"}):
            vault = generate_vault(values)

        self.assertEqual(vault["coefficient_count"], 5 + 8)

    def test_audio_runs_through_dsp_and_unlocks_crypto_vault(self) -> None:
        dsp_result = process_audio_buffer(diverse_voice_like_wav())
        values = formant_values_from_dsp(dsp_result)

        self.assertGreaterEqual(count_distinct_formant_bins(values), 18)
        with patch.dict(os.environ, {"CHABI_SECRET": "CHABI-DEMO"}):
            vault = generate_vault(values)
            plaintext = unlock_vault(values, vault)

        self.assertEqual(plaintext, b"CHABI-DEMO")

    def test_small_formant_drift_still_unlocks(self) -> None:
        baseline = formant_values_from_dsp(dsp_frames_with_distinct_bins())
        drifted = [value + (10 if index % 2 else -10) for index, value in enumerate(baseline)]
        vault = generate_vault(baseline)

        self.assertEqual(unlock_vault(drifted, vault), b"CHABI-DEMO")

    def test_different_formants_are_rejected(self) -> None:
        baseline = formant_values_from_dsp(dsp_frames_with_distinct_bins())
        wrong_voice = [value + 10_000 for value in baseline]
        vault = generate_vault(baseline)

        with self.assertRaises(VaultAuthenticationError):
            unlock_vault(wrong_voice, vault)


if __name__ == "__main__":
    unittest.main()
