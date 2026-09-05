"""
CHAABI - Person 3's FastAPI hub, rebuilt against the REAL contracts from
Person 1 (dsp_engine.py) and Person 2 (crypto_vault.py).

Flow:
  GET  /api/challenge        -> issues a random code-mixed voice prompt
  POST /voice/enroll         -> audio -> DSP -> generate_vault() -> store vault
  POST /voice/authenticate   -> audio + session_id -> DSP -> replay/liveness
                                 gates -> Sarvam STT+intent check -> vault
                                 unlock -> one verdict JSON

Run:
  uvicorn main:app --reload --port 8000
  then open http://127.0.0.1:8000/docs to test everything from the browser.
"""
import logging
import random
import time
import uuid
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chaabi.main")

# --- Person 1 & Person 2's real modules -----------------------------------
from dsp_engine import AudioProcessingError, process_audio_buffer
from crypto_vault import VaultAuthenticationError, generate_vault, unlock_from_dsp_result

from sarvam_client import SarvamError, transcribe_codemix, verify_intent

app = FastAPI(title="CHAABI Auth Hub")

# Tighten this to the frontend's real dev URL before the demo
# (e.g. "http://localhost:5173" for Vite).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- In-memory stores -------------------------------------------------------
# Fine for a hackathon single-process demo.
SESSION_TTL_SECONDS = 120
challenge_sessions: dict[str, dict] = {}   # session_id -> {prompt, created_at}
vault_store: dict[str, dict] = {}          # user_id -> vault dict from Person 2

CHALLENGE_TEMPLATES = [
    "Override code {code} verify fast",
    "Confirm access code {code} abhi",
    "Security clearance {code} chahiye",
    "Unlock sequence {code} ready hai",
]


class ChallengeResponse(BaseModel):
    session_id: str
    prompt: str
    expires_in: int


class EnrollResponse(BaseModel):
    success: bool
    user_id: Optional[str] = None
    message: Optional[str] = None


class AuthResponse(BaseModel):
    authenticated: bool
    message: str
    reason: Optional[str] = None
    transcript: Optional[str] = None


def _cleanup_sessions() -> None:
    now = time.time()
    dead = [sid for sid, s in challenge_sessions.items() if now - s["created_at"] > SESSION_TTL_SECONDS]
    for sid in dead:
        challenge_sessions.pop(sid, None)


def _content_type_or_default(upload: UploadFile) -> str:
    return upload.content_type or "audio/wav"


@app.get("/")
def root():
    return {"status": "ok", "service": "CHAABI FastAPI hub"}


@app.get("/api/challenge", response_model=ChallengeResponse)
def get_challenge():
    """Issue a fresh random code-mixed prompt tied to a new session_id.
    Call this right before /voice/authenticate."""
    _cleanup_sessions()
    code = random.randint(100, 999)
    prompt = random.choice(CHALLENGE_TEMPLATES).format(code=code)
    session_id = str(uuid.uuid4())
    challenge_sessions[session_id] = {"prompt": prompt, "created_at": time.time()}
    return ChallengeResponse(session_id=session_id, prompt=prompt, expires_in=SESSION_TTL_SECONDS)


@app.post("/voice/enroll", response_model=EnrollResponse)
async def enroll(user_id: str = Form(...), audio: UploadFile = File(...)):
    """One-time voice enrollment: DSP -> generate_vault() -> store."""
    audio_bytes = await audio.read()

    try:
        dsp_result = process_audio_buffer(audio_bytes, content_type=_content_type_or_default(audio))
    except AudioProcessingError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    if dsp_result["formants_hz"]["f1"] is None or dsp_result["formants_hz"]["f2"] is None \
            or dsp_result["formants_hz"]["f3"] is None:
        return EnrollResponse(success=False, message="Could not extract enough voice features. Try recording again.")

    vault = generate_vault(dsp_result)
    vault_store[user_id] = vault
    return EnrollResponse(success=True, user_id=user_id, message="Enrollment successful.")


@app.post("/voice/authenticate", response_model=AuthResponse)
async def authenticate(
    user_id: str = Form(...),
    session_id: str = Form(...),
    audio: UploadFile = File(...),
):
    """Full authentication: DSP gates -> Sarvam STT+intent -> vault unlock."""
    _cleanup_sessions()

    session = challenge_sessions.get(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="Unknown or expired session_id")

    vault = vault_store.get(user_id)
    if not vault:
        raise HTTPException(status_code=404, detail=f"No enrolled vault for user_id={user_id!r}")

    audio_bytes = await audio.read()

    # 1. Person 1: DSP - formants, replay, liveness
    try:
        dsp_result = process_audio_buffer(audio_bytes, content_type=_content_type_or_default(audio))
    except AudioProcessingError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # 2. Gate: missing formants
    f = dsp_result["formants_hz"]
    if f["f1"] is None or f["f2"] is None or f["f3"] is None:
        return AuthResponse(authenticated=False, message="Could not extract enough voice features.",
                             reason="DSP_FEATURES_UNAVAILABLE")

    # 3. Gate: replay detected
    if dsp_result["is_replay_attack"]:
        return AuthResponse(authenticated=False, message="Voice verification failed.", reason="REPLAY_DETECTED")

    # 4. Gate: liveness inconclusive - do NOT treat as live just because is_replay_attack is False
    if not dsp_result["liveness_available"]:
        return AuthResponse(authenticated=False, message="Please record again.", reason="LIVENESS_INCONCLUSIVE")

    # 5. Sarvam STT + intent check - does the transcript match the issued challenge?
    try:
        transcript = transcribe_codemix(audio_bytes)
    except SarvamError as e:
        raise HTTPException(status_code=502, detail=f"Sarvam STT error: {e}")

    try:
        intent_ok = verify_intent(challenge_prompt=session["prompt"], transcript=transcript)
    except SarvamError as e:
        raise HTTPException(status_code=502, detail=f"Sarvam LLM error: {e}")

    if not intent_ok:
        return AuthResponse(authenticated=False, message="Challenge phrase not confirmed.",
                             reason="INTENT_MISMATCH", transcript=transcript)

    # 6. Person 2: vault unlock (voice match)
    try:
        plaintext = unlock_from_dsp_result(dsp_result, vault)
    except VaultAuthenticationError:
        return AuthResponse(authenticated=False, message="Voice authentication failed.",
                             reason="VOICE_MISMATCH", transcript=transcript)

    challenge_sessions.pop(session_id, None)  # one-shot challenge
    logger.info("Auth success for user_id=%s, secret len=%d", user_id, len(plaintext))
    return AuthResponse(authenticated=True, message="Voice authentication successful.", transcript=transcript)