"""
Thin wrapper around the Sarvam AI SDK for the two things this module needs:
  1. transcribe_codemix() - speech-to-text on the recorded challenge response
  2. verify_intent()      - LLM check that the transcript matches the challenge

Requires: pip install sarvamai
Requires env var: SARVAM_API_KEY (get one at https://dashboard.sarvam.ai)
"""
import os
import tempfile

from sarvamai import SarvamAI

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
# saaras:v4 is Sarvam's newest STT model (announced with multi-speaker support).
# If your account/SDK version doesn't have v4 yet, fall back to "saaras:v3" -
# both support mode="codemix". Override via env var without touching code.
STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saaras:v4")
LLM_MODEL = os.getenv("SARVAM_LLM_MODEL", "sarvam-105b")


class SarvamError(RuntimeError):
    """Wraps any Sarvam SDK/network error so main.py can catch one type."""
    pass


_client = None


def _get_client() -> SarvamAI:
    global _client
    if _client is None:
        if not SARVAM_API_KEY:
            raise SarvamError(
                "SARVAM_API_KEY is not set. Copy .env.example to .env and "
                "paste your key from https://dashboard.sarvam.ai"
            )
        _client = SarvamAI(api_subscription_key=SARVAM_API_KEY)
    return _client


def transcribe_codemix(audio_bytes: bytes) -> str:
    """Send raw audio bytes to Sarvam STT (code-mixed mode) and return the transcript.

    The SDK wants a file object, so this writes the bytes to a temp .wav file
    first. If your frontend records webm/ogg (typical for the browser
    MediaRecorder API), convert to wav before calling this - see the
    "Audio format" note in README.md.
    """
    client = _get_client()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name
    try:
        with open(tmp_path, "rb") as f:
            response = client.speech_to_text.transcribe(
                file=f,
                model=STT_MODEL,
                language_code="unknown",  # auto-detect, needed for code-mixed speech
                mode="codemix",
            )
        return response.transcript
    except Exception as e:
        raise SarvamError(str(e)) from e
    finally:
        os.unlink(tmp_path)


def verify_intent(challenge_prompt: str, transcript: str) -> bool:
    """Ask sarvam-105b whether the transcript satisfies the issued challenge phrase.

    Returns True/False rather than raw text so main.py doesn't have to
    parse the model's wording.
    """
    client = _get_client()
    system = (
        "You are a strict security verifier. You are given a CHALLENGE phrase "
        "a user was asked to say aloud, and a TRANSCRIPT of what they actually "
        "said (possibly code-mixed Hindi/English, possibly with minor STT "
        "errors). Reply with exactly one word: YES if the transcript conveys "
        "the same meaning as the challenge AND any numbers match exactly, "
        "or NO otherwise. No explanation, no punctuation, just YES or NO."
    )
    user = f"CHALLENGE: {challenge_prompt}\nTRANSCRIPT: {transcript}"
    try:
        response = client.chat.completions(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        answer = response.choices[0].message.content.strip().upper()
        return answer.startswith("YES")
    except Exception as e:
        raise SarvamError(str(e)) from e