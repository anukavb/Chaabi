"""Small, mockable Sarvam AI adapter used by the FastAPI integration."""

from __future__ import annotations

import os
import tempfile


STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
LLM_MODEL = os.getenv("SARVAM_LLM_MODEL", "sarvam-105b")


class SarvamError(RuntimeError):
    """Wrap Sarvam SDK, configuration, and network failures."""


def _client():
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise SarvamError("SARVAM_API_KEY is not configured.")
    try:
        from sarvamai import SarvamAI
    except ImportError as error:
        raise SarvamError("Install the sarvamai package before using live STT.") from error
    return SarvamAI(api_subscription_key=api_key)


def transcribe_codemix(audio_bytes: bytes) -> str:
    """Transcribe WAV bytes using Sarvam's code-mixed speech mode."""
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary_file:
            temporary_file.write(audio_bytes)
            temporary_path = temporary_file.name
        with open(temporary_path, "rb") as audio_file:
            response = _client().speech_to_text.transcribe(
                file=audio_file,
                model=STT_MODEL,
                language_code="unknown",
                mode="codemix",
            )
        return str(response.transcript)
    except SarvamError:
        raise
    except Exception as error:
        raise SarvamError(str(error)) from error
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def verify_intent(challenge_prompt: str, transcript: str) -> bool:
    """Ask Sarvam for a strict semantic challenge/transcript match."""
    system_prompt = (
        "You are a strict security verifier. Reply with exactly YES when the "
        "transcript matches the challenge, including every number; otherwise "
        "reply with exactly NO."
    )
    user_prompt = f"CHALLENGE: {challenge_prompt}\nTRANSCRIPT: {transcript}"
    try:
        response = _client().chat.completions(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        answer = str(response.choices[0].message.content).strip().upper()
        return answer == "YES"
    except SarvamError:
        raise
    except Exception as error:
        raise SarvamError(str(error)) from error
