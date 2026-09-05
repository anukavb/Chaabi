"""CHAABI FastAPI integration hub for DSP, challenge, STT, and crypto."""

from __future__ import annotations

import logging
import random
import time
import uuid
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from crypto_vault import (
    VaultAuthenticationError,
    formant_values_from_dsp,
    generate_vault,
    unlock_vault,
)
from dsp_engine import AudioProcessingError, process_audio_buffer
from sarvam_client import SarvamError, transcribe_codemix, verify_intent


load_dotenv()
logger = logging.getLogger("chaabi.main")

app = FastAPI(title="CHAABI Auth Hub", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SESSION_TTL_SECONDS = 120
challenge_sessions: dict[str, dict[str, Any]] = {}
vault_store: dict[str, dict[str, Any]] = {}

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
    user_id: str | None = None
    message: str
    distinct_formant_bins: int | None = None
    dsp: dict[str, Any] | None = None


class AuthResponse(BaseModel):
    authenticated: bool
    message: str
    reason: str | None = None
    transcript: str | None = None
    dsp: dict[str, Any] | None = None


def _cleanup_sessions() -> None:
    now = time.time()
    expired = [
        session_id
        for session_id, session in challenge_sessions.items()
        if now - float(session["created_at"]) > SESSION_TTL_SECONDS
    ]
    for session_id in expired:
        challenge_sessions.pop(session_id, None)


def _content_type(upload: UploadFile) -> str:
    return upload.content_type or "audio/wav"


def _run_dsp(audio_bytes: bytes, content_type: str) -> dict[str, Any]:
    try:
        return process_audio_buffer(audio_bytes, content_type=content_type)
    except AudioProcessingError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _dsp_gate_reason(dsp_result: dict[str, Any]) -> str | None:
    if not dsp_result["audio_quality"]["speech_detected"]:
        return "DSP_FEATURES_UNAVAILABLE"
    if not dsp_result["formant_frames"]:
        return "DSP_FEATURES_UNAVAILABLE"
    if dsp_result["is_replay_attack"]:
        return "REPLAY_DETECTED"
    if not dsp_result["liveness_available"]:
        return "LIVENESS_INCONCLUSIVE"
    return None


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "service": "CHAABI FastAPI hub"}


@app.get("/api/challenge", response_model=ChallengeResponse)
def get_challenge() -> ChallengeResponse:
    _cleanup_sessions()
    prompt = random.choice(CHALLENGE_TEMPLATES).format(code=random.randint(100, 999))
    session_id = str(uuid.uuid4())
    challenge_sessions[session_id] = {"prompt": prompt, "created_at": time.time()}
    return ChallengeResponse(
        session_id=session_id,
        prompt=prompt,
        expires_in=SESSION_TTL_SECONDS,
    )


@app.post("/voice/enroll", response_model=EnrollResponse)
async def enroll(
    user_id: str = Form(...),
    audio: UploadFile = File(...),
) -> EnrollResponse:
    audio_bytes = await audio.read()
    dsp_result = _run_dsp(audio_bytes, _content_type(audio))
    gate_reason = _dsp_gate_reason(dsp_result)
    if gate_reason:
        return EnrollResponse(
            success=False,
            message="Recording failed DSP quality or liveness checks.",
            dsp=dsp_result,
        )

    formants = formant_values_from_dsp(dsp_result)
    try:
        vault = generate_vault(formants)
    except (ValueError, VaultAuthenticationError) as error:
        return EnrollResponse(
            success=False,
            message=str(error),
            distinct_formant_bins=len({round(value / 25) for value in formants}),
            dsp=dsp_result,
        )

    vault_store[user_id] = vault
    return EnrollResponse(
        success=True,
        user_id=user_id,
        message="Enrollment successful.",
        distinct_formant_bins=len({round(value / 25) for value in formants}),
        dsp=dsp_result,
    )


@app.post("/voice/authenticate", response_model=AuthResponse)
async def authenticate(
    user_id: str = Form(...),
    session_id: str = Form(...),
    audio: UploadFile = File(...),
) -> AuthResponse:
    _cleanup_sessions()
    session = challenge_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=400, detail="Unknown or expired session_id.")
    vault = vault_store.get(user_id)
    if vault is None:
        raise HTTPException(status_code=404, detail="No enrolled vault for this user.")

    audio_bytes = await audio.read()
    dsp_result = _run_dsp(audio_bytes, _content_type(audio))
    gate_reason = _dsp_gate_reason(dsp_result)
    if gate_reason:
        return AuthResponse(
            authenticated=False,
            message="Voice verification failed DSP checks.",
            reason=gate_reason,
            dsp=dsp_result,
        )

    try:
        transcript = transcribe_codemix(audio_bytes)
        intent_matches = verify_intent(str(session["prompt"]), transcript)
    except SarvamError as error:
        raise HTTPException(status_code=502, detail=f"Sarvam error: {error}") from error

    if not intent_matches:
        return AuthResponse(
            authenticated=False,
            message="Challenge phrase not confirmed.",
            reason="INTENT_MISMATCH",
            transcript=transcript,
            dsp=dsp_result,
        )

    try:
        plaintext = unlock_vault(formant_values_from_dsp(dsp_result), vault)
    except VaultAuthenticationError:
        return AuthResponse(
            authenticated=False,
            message="Voice authentication failed.",
            reason="VOICE_MISMATCH",
            transcript=transcript,
            dsp=dsp_result,
        )

    challenge_sessions.pop(session_id, None)
    logger.info("Authentication succeeded for user_id=%s", user_id)
    return AuthResponse(
        authenticated=True,
        message=f"Voice authenticated; protected payload recovered ({len(plaintext)} bytes).",
        transcript=transcript,
        dsp=dsp_result,
    )
