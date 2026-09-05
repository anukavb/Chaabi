"""Small, mockable Sarvam AI adapter used by the FastAPI integration."""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata


STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
STT_LANGUAGE_CODE = os.getenv("SARVAM_STT_LANGUAGE_CODE", "en-IN")
STT_MODE = os.getenv("SARVAM_STT_MODE", "transcribe")
LLM_MODEL = os.getenv("SARVAM_LLM_MODEL", "sarvam-105b")

DIGIT_WORDS = {
    "zero": "0",
    "oh": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}


class SarvamError(RuntimeError):
    """Wrap Sarvam SDK, configuration, and network failures."""


def normalize_challenge_text(text: str) -> list[str]:
    """Normalize punctuation, common CHAABI spellings, and spoken digits."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens = re.findall(r"[a-z]+|\d+", normalized)
    result: list[str] = []
    for token in tokens:
        if token in {"chabi", "chaabi"}:
            result.append("chaabi")
        elif token in DIGIT_WORDS:
            result.append(DIGIT_WORDS[token])
        elif token.isdigit():
            result.extend(token)
        else:
            result.append(token)
    return result


def challenge_matches_transcript(challenge_prompt: str, transcript: str) -> bool:
    """Perform the primary deterministic security comparison."""
    return normalize_challenge_text(challenge_prompt) == normalize_challenge_text(transcript)


def challenge_digits_match(challenge_prompt: str, transcript: str) -> bool:
    """Ensure an LLM can never override a changed challenge number."""
    expected = [token for token in normalize_challenge_text(challenge_prompt) if token.isdigit()]
    actual = [token for token in normalize_challenge_text(transcript) if token.isdigit()]
    return bool(expected) and expected == actual


def _client():
    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise SarvamError("SARVAM_API_KEY is not configured.")
    try:
        from sarvamai import SarvamAI
    except ImportError as error:
        raise SarvamError("Install the sarvamai package before using live STT.") from error
    return SarvamAI(api_subscription_key=api_key)


def transcribe_english(audio_bytes: bytes) -> str:
    """Transcribe the app's English-only WAV challenge using Sarvam."""
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary_file:
            temporary_file.write(audio_bytes)
            temporary_path = temporary_file.name
        with open(temporary_path, "rb") as audio_file:
            response = _client().speech_to_text.transcribe(
                file=audio_file,
                model=STT_MODEL,
                language_code=STT_LANGUAGE_CODE,
                mode=STT_MODE,
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
