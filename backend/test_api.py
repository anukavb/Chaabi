"""
Manual smoke test against a RUNNING server (uvicorn main:app --reload).

Usage:
    python test_api.py enroll   path\\to\\your_voice.wav
    python test_api.py auth     path\\to\\your_voice.wav

Record yourself once with `enroll`, then run `auth` with a fresh recording
(ideally saying whatever /api/challenge gives you) to see a real verdict.
"""
import sys

import requests

BASE_URL = "http://127.0.0.1:8000"
USER_ID = "chir"


def enroll(audio_path: str):
    with open(audio_path, "rb") as f:
        r = requests.post(f"{BASE_URL}/voice/enroll", data={"user_id": USER_ID},
                           files={"audio": (audio_path, f, "audio/wav")})
    print("Enroll:", r.status_code, r.json())


def authenticate(audio_path: str):
    c = requests.get(f"{BASE_URL}/api/challenge")
    c.raise_for_status()
    challenge = c.json()
    print("Say this out loud, then record:", challenge["prompt"])

    with open(audio_path, "rb") as f:
        r = requests.post(
            f"{BASE_URL}/voice/authenticate",
            data={"user_id": USER_ID, "session_id": challenge["session_id"]},
            files={"audio": (audio_path, f, "audio/wav")},
        )
    print("Authenticate:", r.status_code, r.json())


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("enroll", "auth"):
        print("Usage: python test_api.py [enroll|auth] path\\to\\audio.wav")
        sys.exit(1)
    (enroll if sys.argv[1] == "enroll" else authenticate)(sys.argv[2])