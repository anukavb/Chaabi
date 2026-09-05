"""End-to-end tests from uploaded WAV bytes through DSP and crypto."""

from io import BytesIO
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from scipy.io import wavfile

import main


def voice_wav(sample_rate: int = 48_000, replay_like: bool = False) -> bytes:
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
    time_axis = np.arange(int(sample_rate * 0.16)) / sample_rate
    segments = []
    for f1, f2, f3 in formant_sets:
        segment = (
            0.24 * np.sin(2 * np.pi * f1 * time_axis)
            + 0.18 * np.sin(2 * np.pi * f2 * time_axis)
            + 0.12 * np.sin(2 * np.pi * f3 * time_axis)
        )
        if replay_like and sample_rate > 36_000:
            segment += 0.40 * np.sin(2 * np.pi * 18_000 * time_axis)
        segments.append(segment)
    output = BytesIO()
    wavfile.write(
        output,
        sample_rate,
        np.int16(np.clip(np.concatenate(segments), -1.0, 1.0) * 32_767),
    )
    return output.getvalue()


def stable_three_formant_wav() -> bytes:
    sample_rate = 48_000
    time_axis = np.arange(sample_rate) / sample_rate
    audio = (
        0.25 * np.sin(2 * np.pi * 500 * time_axis)
        + 0.18 * np.sin(2 * np.pi * 1_500 * time_axis)
        + 0.12 * np.sin(2 * np.pi * 2_500 * time_axis)
    )
    output = BytesIO()
    wavfile.write(output, sample_rate, np.int16(audio * 32_767))
    return output.getvalue()


class ApiEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        main.challenge_sessions.clear()
        main.vault_store.clear()
        self.client = TestClient(main.app)
        self.live_audio = voice_wav()

    def _enroll(self) -> dict:
        response = self.client.post(
            "/voice/enroll",
            data={"user_id": "test-user"},
            files={"audio": ("voice.wav", self.live_audio, "audio/wav")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        return response.json()

    def _challenge(self) -> dict:
        response = self.client.get("/api/challenge")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_complete_enroll_challenge_authenticate_flow(self) -> None:
        enrollment = self._enroll()
        challenge = self._challenge()

        with (
            patch("main.transcribe_codemix", return_value=challenge["prompt"]),
            patch("main.verify_intent", return_value=True),
        ):
            response = self.client.post(
                "/voice/authenticate",
                data={"user_id": "test-user", "session_id": challenge["session_id"]},
                files={"audio": ("voice.wav", self.live_audio, "audio/wav")},
            )

        body = response.json()
        self.assertTrue(body["authenticated"])
        self.assertGreaterEqual(enrollment["distinct_formant_bins"], 18)
        self.assertGreater(len(body["dsp"]["formant_frames"]), 6)
        self.assertNotIn(challenge["session_id"], main.challenge_sessions)

        reused = self.client.post(
            "/voice/authenticate",
            data={"user_id": "test-user", "session_id": challenge["session_id"]},
            files={"audio": ("voice.wav", self.live_audio, "audio/wav")},
        )
        self.assertEqual(reused.status_code, 400)

    def test_replay_is_rejected_before_sarvam(self) -> None:
        self._enroll()
        challenge = self._challenge()

        with patch("main.transcribe_codemix") as transcribe:
            response = self.client.post(
                "/voice/authenticate",
                data={"user_id": "test-user", "session_id": challenge["session_id"]},
                files={"audio": ("replay.wav", voice_wav(replay_like=True), "audio/wav")},
            )

        self.assertEqual(response.json()["reason"], "REPLAY_DETECTED")
        transcribe.assert_not_called()

    def test_low_sample_rate_is_inconclusive(self) -> None:
        self._enroll()
        challenge = self._challenge()
        response = self.client.post(
            "/voice/authenticate",
            data={"user_id": "test-user", "session_id": challenge["session_id"]},
            files={"audio": ("voice.wav", voice_wav(sample_rate=16_000), "audio/wav")},
        )

        self.assertEqual(response.json()["reason"], "LIVENESS_INCONCLUSIVE")

    def test_intent_mismatch_is_rejected(self) -> None:
        self._enroll()
        challenge = self._challenge()
        with (
            patch("main.transcribe_codemix", return_value="wrong code"),
            patch("main.verify_intent", return_value=False),
        ):
            response = self.client.post(
                "/voice/authenticate",
                data={"user_id": "test-user", "session_id": challenge["session_id"]},
                files={"audio": ("voice.wav", self.live_audio, "audio/wav")},
            )

        self.assertEqual(response.json()["reason"], "INTENT_MISMATCH")

    def test_invalid_audio_returns_422(self) -> None:
        response = self.client.post(
            "/voice/enroll",
            data={"user_id": "test-user"},
            files={"audio": ("broken.wav", b"RIFF-not-valid", "audio/wav")},
        )

        self.assertEqual(response.status_code, 422)

    def test_unknown_session_and_user_are_rejected(self) -> None:
        unknown_session = self.client.post(
            "/voice/authenticate",
            data={"user_id": "test-user", "session_id": "missing"},
            files={"audio": ("voice.wav", self.live_audio, "audio/wav")},
        )
        self.assertEqual(unknown_session.status_code, 400)

        challenge = self._challenge()
        unknown_user = self.client.post(
            "/voice/authenticate",
            data={"user_id": "missing", "session_id": challenge["session_id"]},
            files={"audio": ("voice.wav", self.live_audio, "audio/wav")},
        )
        self.assertEqual(unknown_user.status_code, 404)

    def test_enrollment_rejects_too_few_distinct_bins(self) -> None:
        response = self.client.post(
            "/voice/enroll",
            data={"user_id": "test-user"},
            files={"audio": ("stable.wav", stable_three_formant_wav(), "audio/wav")},
        )

        body = response.json()
        self.assertFalse(body["success"])
        self.assertLess(body["distinct_formant_bins"], 18)
        self.assertIn("18 distinct", body["message"])

    def test_sarvam_failure_returns_502(self) -> None:
        self._enroll()
        challenge = self._challenge()
        with patch(
            "main.transcribe_codemix",
            side_effect=main.SarvamError("service unavailable"),
        ):
            response = self.client.post(
                "/voice/authenticate",
                data={"user_id": "test-user", "session_id": challenge["session_id"]},
                files={"audio": ("voice.wav", self.live_audio, "audio/wav")},
            )

        self.assertEqual(response.status_code, 502)

    def test_vault_mismatch_is_reported(self) -> None:
        self._enroll()
        challenge = self._challenge()
        with (
            patch("main.transcribe_codemix", return_value=challenge["prompt"]),
            patch("main.verify_intent", return_value=True),
            patch(
                "main.unlock_vault",
                side_effect=main.VaultAuthenticationError("different voice"),
            ),
        ):
            response = self.client.post(
                "/voice/authenticate",
                data={"user_id": "test-user", "session_id": challenge["session_id"]},
                files={"audio": ("voice.wav", self.live_audio, "audio/wav")},
            )

        self.assertEqual(response.json()["reason"], "VOICE_MISMATCH")

    def test_expired_challenge_is_rejected(self) -> None:
        challenge = self._challenge()
        main.challenge_sessions[challenge["session_id"]]["created_at"] = 0

        response = self.client.post(
            "/voice/authenticate",
            data={"user_id": "test-user", "session_id": challenge["session_id"]},
            files={"audio": ("voice.wav", self.live_audio, "audio/wav")},
        )

        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
