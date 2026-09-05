"""Manual smoke test against a running ``uvicorn main:app --reload`` API.

Usage:
    python test_api.py signup
    python test_api.py enroll first.wav second.wav third.wav
    python test_api.py auth challenge.wav

Change USER_ID and PASSWORD below before using this helper.
"""

from __future__ import annotations

import sys

import requests


BASE_URL = "http://localhost:8000"
USER_ID = "chir"
PASSWORD = "replace-this-demo-password"
CLIENT = requests.Session()


def account(action: str) -> dict:
    response = CLIENT.post(
        f"{BASE_URL}/api/accounts/{action}",
        json={"user_id": USER_ID, "password": PASSWORD},
    )
    response.raise_for_status()
    return response.json()


def enroll(audio_paths: list[str]) -> None:
    account("login")
    handles = [open(path, "rb") for path in audio_paths]
    try:
        files = {
            f"audio_{index}": (path, handle, "audio/wav")
            for index, (path, handle) in enumerate(zip(audio_paths, handles), start=1)
        }
        response = CLIENT.post(
            f"{BASE_URL}/voice/enroll",
            data={"replace_existing": "true"},
            files=files,
        )
    finally:
        for handle in handles:
            handle.close()
    print("Enroll:", response.status_code, response.json())


def authenticate(audio_path: str) -> None:
    account("login")
    challenge_response = CLIENT.get(f"{BASE_URL}/api/challenge")
    challenge_response.raise_for_status()
    challenge = challenge_response.json()
    print("Say this out loud, then record:", challenge["text"])

    with open(audio_path, "rb") as handle:
        response = CLIENT.post(
            f"{BASE_URL}/voice/authenticate",
            data={"challenge_id": challenge["challenge_id"]},
            files={"audio": (audio_path, handle, "audio/wav")},
        )
    print("Authenticate:", response.status_code, response.json())


if __name__ == "__main__":
    valid = (
        (sys.argv[1:2] == ["signup"] and len(sys.argv) == 2)
        or (sys.argv[1:2] == ["enroll"] and len(sys.argv) == 5)
        or (sys.argv[1:2] == ["auth"] and len(sys.argv) == 3)
    )
    if not valid:
        print("Usage: python test_api.py signup")
        print("   or: python test_api.py enroll first.wav second.wav third.wav")
        print("   or: python test_api.py auth challenge.wav")
        sys.exit(1)
    if sys.argv[1] == "signup":
        print("Signup:", account("signup"))
    elif sys.argv[1] == "enroll":
        enroll(sys.argv[2:5])
    else:
        authenticate(sys.argv[2])
