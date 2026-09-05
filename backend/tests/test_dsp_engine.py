"""Smoke tests for the first Person 1 milestone."""

from io import BytesIO
import json
import unittest

import numpy as np
from scipy.io import wavfile

from dsp_engine import AudioProcessingError, process_audio_buffer


def make_test_wav(
    sample_rate: int = 48_000,
    duration: float = 0.5,
    replay_like: bool = False,
) -> bytes:
    time = np.arange(int(sample_rate * duration)) / sample_rate
    test_signal = (
        0.25 * np.sin(2 * np.pi * 500 * time)
        + 0.18 * np.sin(2 * np.pi * 1_500 * time)
        + 0.12 * np.sin(2 * np.pi * 2_500 * time)
    )
    if replay_like and sample_rate > 36_000:
        test_signal += 0.45 * np.sin(2 * np.pi * 18_000 * time)
    samples = np.int16(np.clip(test_signal, -1.0, 1.0) * 32_767)
    buffer = BytesIO()
    wavfile.write(buffer, sample_rate, samples)
    return buffer.getvalue()


def encode_wav(samples: np.ndarray, sample_rate: int = 48_000) -> bytes:
    buffer = BytesIO()
    wavfile.write(buffer, sample_rate, samples)
    return buffer.getvalue()


class DspEngineTests(unittest.TestCase):
    def test_48khz_wav_returns_stable_contract(self) -> None:
        result = process_audio_buffer(make_test_wav())

        self.assertEqual(result["audio_quality"]["sample_rate"], 48_000)
        self.assertIn("formant_frames", result)
        self.assertIn("formant_summary", result)
        self.assertIn("liveness_score", result)
        self.assertIn("reason_codes", result)
        self.assertTrue(result["liveness_available"])
        self.assertIsNotNone(result["features"]["high_frequency_energy_ratio"])
        self.assertFalse(result["is_replay_attack"])
        json.dumps(result)

    def test_16khz_wav_reports_ultrasonic_analysis_unavailable(self) -> None:
        result = process_audio_buffer(make_test_wav(sample_rate=16_000))

        self.assertFalse(result["liveness_available"])
        self.assertIsNone(result["features"]["high_frequency_energy_ratio"])
        self.assertIsNone(result["liveness_score"])
        self.assertIn("ULTRASONIC_ANALYSIS_UNAVAILABLE", result["reason_codes"])

    def test_empty_audio_is_rejected(self) -> None:
        with self.assertRaisesRegex(AudioProcessingError, "empty"):
            process_audio_buffer(b"")

    def test_raw_pcm_requires_sample_rate(self) -> None:
        with self.assertRaisesRegex(AudioProcessingError, "sample_rate"):
            process_audio_buffer(b"\x00\x00" * 2_000, content_type="audio/pcm")

    def test_raw_pcm_with_sample_rate_is_accepted(self) -> None:
        wav_bytes = make_test_wav(sample_rate=16_000)
        _, samples = wavfile.read(BytesIO(wav_bytes))

        result = process_audio_buffer(
            samples.astype("<i2").tobytes(),
            content_type="audio/pcm",
            sample_rate=16_000,
        )

        self.assertEqual(result["audio_quality"]["sample_rate"], 16_000)
        self.assertTrue(result["audio_quality"]["speech_detected"])

    def test_malformed_wav_is_rejected(self) -> None:
        with self.assertRaisesRegex(AudioProcessingError, "valid WAV"):
            process_audio_buffer(b"RIFF" + b"not-a-wav" * 100)

    def test_silence_is_not_detected_as_speech(self) -> None:
        silence = np.zeros(48_000, dtype=np.int16)
        result = process_audio_buffer(encode_wav(silence))

        self.assertFalse(result["audio_quality"]["speech_detected"])
        self.assertFalse(result["liveness_available"])
        self.assertIsNone(result["liveness_score"])
        self.assertEqual(
            result["formant_summary"],
            {"f1_hz": None, "f2_hz": None, "f3_hz": None},
        )
        self.assertEqual(result["formant_frames"], [])
        self.assertIn("LOW_AUDIO_LEVEL", result["reason_codes"])
        self.assertIn("NO_SPEECH_DETECTED", result["reason_codes"])

    def test_clipped_audio_is_reported(self) -> None:
        samples = np.full(48_000, 32_767, dtype=np.int16)
        samples[1::2] = -32_768
        result = process_audio_buffer(encode_wav(samples))

        self.assertTrue(result["audio_quality"]["clipping_detected"])
        self.assertIn("EXCESSIVE_CLIPPING", result["reason_codes"])

    def test_stereo_wav_is_converted_to_mono(self) -> None:
        mono_bytes = make_test_wav()
        sample_rate, mono = wavfile.read(BytesIO(mono_bytes))
        stereo = np.column_stack((mono, mono))

        result = process_audio_buffer(encode_wav(stereo, sample_rate))

        self.assertTrue(result["audio_quality"]["speech_detected"])
        self.assertIsNotNone(result["formant_summary"]["f1_hz"])

    def test_short_audio_is_rejected(self) -> None:
        short_audio = np.zeros(1_000, dtype=np.int16)
        with self.assertRaisesRegex(AudioProcessingError, "100 ms"):
            process_audio_buffer(encode_wav(short_audio, sample_rate=48_000))

    def test_low_amplitude_audio_is_not_accepted_as_speech(self) -> None:
        time = np.arange(48_000) / 48_000
        quiet = np.int16(20 * np.sin(2 * np.pi * 200 * time))
        result = process_audio_buffer(encode_wav(quiet))

        self.assertFalse(result["audio_quality"]["speech_detected"])
        self.assertIn("LOW_AUDIO_LEVEL", result["reason_codes"])

    def test_44100hz_wav_is_supported(self) -> None:
        result = process_audio_buffer(make_test_wav(sample_rate=44_100))

        self.assertEqual(result["audio_quality"]["sample_rate"], 44_100)
        self.assertTrue(result["audio_quality"]["speech_detected"])
        self.assertIsNotNone(result["formant_summary"]["f1_hz"])

    def test_replay_like_high_frequency_energy_is_flagged(self) -> None:
        result = process_audio_buffer(make_test_wav(replay_like=True))

        self.assertTrue(result["liveness_available"])
        self.assertTrue(result["is_replay_attack"])
        self.assertLessEqual(result["liveness_score"], 0.45)
        self.assertIn("ELEVATED_HIGH_FREQUENCY_ENERGY", result["reason_codes"])
        self.assertIn("HIGH_REPLAY_RISK", result["reason_codes"])

    def test_response_follows_teammate_contract(self) -> None:
        result = process_audio_buffer(make_test_wav())

        self.assertEqual(
            set(result),
            {
                "formant_frames",
                "formant_summary",
                "liveness_score",
                "is_replay_attack",
                "liveness_available",
                "audio_quality",
                "features",
                "reason_codes",
            },
        )
        self.assertEqual(
            set(result["audio_quality"]),
            {
                "sample_rate",
                "duration_ms",
                "speech_detected",
                "clipping_detected",
                "peak",
                "rms",
            },
        )
        self.assertEqual(set(result["features"]), {"high_frequency_energy_ratio"})
        self.assertGreater(len(result["formant_frames"]), 0)
        self.assertEqual(
            set(result["formant_frames"][0]),
            {"frame_id", "f1_hz", "f2_hz", "f3_hz", "confidence"},
        )


if __name__ == "__main__":
    unittest.main()
