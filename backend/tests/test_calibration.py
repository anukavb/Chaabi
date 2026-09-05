"""Synthetic tests for the Phase 4 calibration workflow."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import numpy as np
from scipy.io import wavfile

from calibrate_dsp import CalibrationError, evaluate_dataset, recommend_threshold


def calibration_wav(replay_like: bool) -> bytes:
    sample_rate = 48_000
    time = np.arange(sample_rate // 2) / sample_rate
    audio = (
        0.25 * np.sin(2 * np.pi * 500 * time)
        + 0.18 * np.sin(2 * np.pi * 1_500 * time)
        + 0.12 * np.sin(2 * np.pi * 2_500 * time)
    )
    if replay_like:
        audio += 0.45 * np.sin(2 * np.pi * 18_000 * time)
    output = BytesIO()
    wavfile.write(output, sample_rate, np.int16(audio * 32_767))
    return output.getvalue()


class CalibrationTests(unittest.TestCase):
    def test_dataset_evaluation_and_threshold_recommendation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "live").mkdir()
            (root / "replay").mkdir()
            (root / "live" / "speaker-name-is-not-exported.wav").write_bytes(
                calibration_wav(False)
            )
            (root / "replay" / "speaker-name-is-not-exported.wav").write_bytes(
                calibration_wav(True)
            )

            rows = evaluate_dataset(root)
            recommendation = recommend_threshold(rows)

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["trial_id"] for row in rows}, {"live-001", "replay-002"})
        self.assertNotIn("speaker-name", str(rows))
        self.assertIsNotNone(recommendation)
        self.assertEqual(recommendation["accuracy"], 1.0)

    def test_empty_dataset_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            with self.assertRaisesRegex(CalibrationError, "No WAV files"):
                evaluate_dataset(Path(temporary_directory))


if __name__ == "__main__":
    unittest.main()
