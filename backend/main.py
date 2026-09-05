"""FastAPI integration hub for the CHAABI voice-authentication prototype."""

from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import logging
import os
import re
import secrets
import time
import uuid
from typing import Any

from dotenv import load_dotenv

# DSP calibration values are read while the internal modules are imported.
load_dotenv()

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from crypto_vault import (
    VaultAuthenticationError,
    formant_values_from_dsp,
    generate_vault_from_bins,
    required_feature_count,
    stable_formant_bins_from_dsp,
    unlock_vault_with_details,
)
from dsp_engine import AudioProcessingError, extract_speaker_embedding, process_audio_buffer
from sarvam_client import (
    SarvamError,
    challenge_digits_match,
    challenge_matches_transcript,
    transcribe_english,
    verify_intent,
)
from storage import (
    AccountAlreadyExistsError,
    ActiveUserConflictError,
    VaultAlreadyExistsError,
    create_account_and_session,
    end_device_session,
    initialize_database,
    load_account_credentials,
    load_vault,
    resolve_device_session,
    save_vault,
    start_device_session,
    vault_exists,
)
from speaker_verification import (
    PROFILE_VERSION,
    SpeakerVerificationError,
    build_speaker_profile,
    compare_speaker,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chaabi.main")

CHALLENGE_TTL_SECONDS = int(
    os.getenv("CHAABI_CHALLENGE_TTL_SECONDS", os.getenv("CHAABI_SESSION_TTL_SECONDS", "120"))
)
ACCOUNT_SESSION_IDLE_TTL_SECONDS = int(
    os.getenv("CHAABI_ACCOUNT_SESSION_IDLE_TTL_SECONDS", "900")
)
ACCOUNT_SESSION_ABSOLUTE_TTL_SECONDS = int(
    os.getenv("CHAABI_ACCOUNT_SESSION_ABSOLUTE_TTL_SECONDS", "28800")
)
SESSION_COOKIE_NAME = "chaabi_session"
SESSION_COOKIE_SECURE = os.getenv("CHAABI_SESSION_COOKIE_SECURE", "false").lower() == "true"
MAX_AUDIO_BYTES = int(os.getenv("CHAABI_MAX_AUDIO_BYTES", str(8 * 1024 * 1024)))
MIN_AUDIO_DURATION_MS = float(os.getenv("CHAABI_MIN_AUDIO_DURATION_MS", "1000"))
MAX_AUDIO_DURATION_MS = float(os.getenv("CHAABI_MAX_AUDIO_DURATION_MS", "8000"))
AUTH_FAILURE_LIMIT = int(os.getenv("CHAABI_AUTH_FAILURE_LIMIT", "5"))
AUTH_FAILURE_WINDOW_SECONDS = int(
    os.getenv("CHAABI_AUTH_FAILURE_WINDOW_SECONDS", "300")
)
DSP_VERSION = "lpc-formants-mfcc-multitemplate-v3"
ENROLLMENT_RECORDINGS = 3
ENROLLMENT_MINIMUM_SUPPORT = 2
ENROLLMENT_PROMPTS = (
    "Please say access code one two three",
    "Please say access code four five six",
    "Please say access code seven eight nine",
)
ENROLLMENT_PROMPT = ENROLLMENT_PROMPTS[0]
CHALLENGE_PREFIX = "Please say access code"
DIGIT_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
INCONCLUSIVE_LIVENESS_SCORE = float(os.getenv("CHAABI_INCONCLUSIVE_LIVENESS_SCORE", "0.70"))

challenge_sessions: dict[str, dict[str, Any]] = {}
authentication_failures: dict[tuple[str, str], list[float]] = {}
credential_failures: dict[tuple[str, str], list[float]] = {}
USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="CHAABI Auth Hub", version="1.0.0", lifespan=lifespan)

allowed_origins = [
    value.strip()
    for value in os.getenv(
        "CHAABI_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if value.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    allow_credentials=True,
    expose_headers=["X-Session-Expires-In"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    session_expires_at = getattr(request.state, "session_expires_at", None)
    if session_expires_at is not None:
        response.headers["X-Session-Expires-In"] = str(
            max(0, int(session_expires_at) - int(time.time()))
        )
    return response


class ConfigResponse(BaseModel):
    enrollment_prompt: str
    enrollment_prompts: list[str]
    enrollment_recordings: int
    required_genuine_points: int
    preferred_sample_rate: int


class ChallengeResponse(BaseModel):
    challenge_id: str
    text: str
    expires_in_seconds: int


class CredentialsRequest(BaseModel):
    user_id: str
    password: str = Field(min_length=10, max_length=128)


class SessionResponse(BaseModel):
    authenticated: bool
    user_id: str | None = None
    expires_in_seconds: int = 0
    absolute_expires_in_seconds: int = 0
    has_voice_enrollment: bool = False


class EnrollResponse(BaseModel):
    enrolled: bool
    user_id: str
    reason: str
    stable_bin_count: int
    required_genuine_points: int
    vault_points: int = 0
    genuine_points: int = 0
    speaker_threshold: float | None = None
    enrollment_voice_consistency: float | None = None


class SpeakerResult(BaseModel):
    matched: bool
    similarity: float | None = None
    threshold: float | None = None
    template_similarities: list[float] = Field(default_factory=list)
    error: str | None = None


class CryptoResult(BaseModel):
    vault_unlocked: bool
    matched_points: int
    required_points: int
    error: str | None = None
    confidence: float | None = None


class AuthResponse(BaseModel):
    authenticated: bool
    message: str
    reason: str
    transcript: str | None = None
    challenge_matched: bool = False
    dsp: dict[str, Any] | None = None
    speaker: SpeakerResult | None = None
    crypto: CryptoResult | None = None


def _clean_user_id(user_id: str) -> str:
    cleaned = user_id.strip()
    if not USER_ID_PATTERN.fullmatch(cleaned):
        raise HTTPException(
            status_code=422,
            detail=(
                "user_id must contain 1 to 64 letters, numbers, dots, "
                "underscores, or hyphens"
            ),
        )
    return cleaned


def _authentication_key(request: Request, user_id: str) -> tuple[str, str]:
    client_ip = request.client.host if request.client else "unknown"
    return user_id, client_ip


def _active_failures(key: tuple[str, str]) -> list[float]:
    cutoff = time.time() - AUTH_FAILURE_WINDOW_SECONDS
    active = [timestamp for timestamp in authentication_failures.get(key, []) if timestamp >= cutoff]
    if active:
        authentication_failures[key] = active
    else:
        authentication_failures.pop(key, None)
    return active


def _enforce_authentication_limit(key: tuple[str, str]) -> None:
    failures = _active_failures(key)
    if len(failures) < AUTH_FAILURE_LIMIT:
        return
    retry_after = max(1, int(failures[0] + AUTH_FAILURE_WINDOW_SECONDS - time.time()))
    raise HTTPException(
        status_code=429,
        detail="Too many failed authentication attempts. Try again later.",
        headers={"Retry-After": str(retry_after)},
    )


def _record_authentication_failure(key: tuple[str, str], reason: str) -> None:
    authentication_failures.setdefault(key, []).append(time.time())
    logger.warning("Authentication denied; reason=%s", reason)


def _enforce_credential_limit(key: tuple[str, str]) -> None:
    cutoff = time.time() - AUTH_FAILURE_WINDOW_SECONDS
    failures = [
        timestamp
        for timestamp in credential_failures.get(key, [])
        if timestamp >= cutoff
    ]
    if failures:
        credential_failures[key] = failures
    else:
        credential_failures.pop(key, None)
    if len(failures) >= AUTH_FAILURE_LIMIT:
        retry_after = max(
            1, int(failures[0] + AUTH_FAILURE_WINDOW_SECONDS - time.time())
        )
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


async def _read_audio_upload(upload: UploadFile) -> bytes:
    audio_bytes = await upload.read(MAX_AUDIO_BYTES + 1)
    if not audio_bytes:
        raise HTTPException(status_code=422, detail="Audio upload is empty.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio upload exceeds the size limit.")
    return audio_bytes


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _password_digest(password: str, salt: bytes) -> str:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    ).hex()


def _new_session_values(now: int) -> tuple[str, str, int, int]:
    raw_token = secrets.token_urlsafe(32)
    return (
        raw_token,
        _token_hash(raw_token),
        now + ACCOUNT_SESSION_IDLE_TTL_SECONDS,
        now + ACCOUNT_SESSION_ABSOLUTE_TTL_SECONDS,
    )


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=ACCOUNT_SESSION_ABSOLUTE_TTL_SECONDS,
        httponly=True,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def _session_response(session: dict[str, int | str]) -> SessionResponse:
    now = int(time.time())
    user_id = str(session["user_id"])
    return SessionResponse(
        authenticated=True,
        user_id=user_id,
        expires_in_seconds=max(0, int(session["idle_expires_at"]) - now),
        absolute_expires_in_seconds=max(
            0, int(session["absolute_expires_at"]) - now
        ),
        has_voice_enrollment=vault_exists(user_id),
    )


def _require_account_session(request: Request, *, touch: bool = True) -> str:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        raise HTTPException(status_code=401, detail="Please log in to continue.")
    session = resolve_device_session(
        _token_hash(raw_token),
        int(time.time()),
        idle_ttl_seconds=ACCOUNT_SESSION_IDLE_TTL_SECONDS,
        touch=touch,
    )
    if session is None:
        raise HTTPException(
            status_code=401, detail="Your session has expired. Please log in again."
        )
    request.state.session_expires_at = int(session["idle_expires_at"])
    return str(session["user_id"])


def _cleanup_challenges() -> None:
    cutoff = time.time() - CHALLENGE_TTL_SECONDS
    expired = [
        challenge_id
        for challenge_id, session in challenge_sessions.items()
        if float(session["created_at"]) < cutoff
    ]
    for challenge_id in expired:
        challenge_sessions.pop(challenge_id, None)


def _content_type(upload: UploadFile) -> str:
    return upload.content_type or "audio/wav"


def _quality_reason(dsp_result: dict[str, Any], require_liveness: bool) -> str | None:
    quality = dsp_result["audio_quality"]
    duration_ms = float(quality["duration_ms"])
    if duration_ms < MIN_AUDIO_DURATION_MS:
        return "AUDIO_TOO_SHORT"
    if duration_ms > MAX_AUDIO_DURATION_MS:
        return "AUDIO_TOO_LONG"
    if not quality["speech_detected"]:
        return "NO_SPEECH_DETECTED"
    if quality["clipping_detected"]:
        return "EXCESSIVE_CLIPPING"
    if not dsp_result["formant_frames"]:
        return "DSP_FEATURES_UNAVAILABLE"
    if dsp_result["is_replay_attack"]:
        return "REPLAY_DETECTED"
    if require_liveness and not dsp_result["liveness_available"]:
        return "LIVENESS_INCONCLUSIVE"
    score = dsp_result.get("liveness_score")
    if require_liveness and score is not None and float(score) < INCONCLUSIVE_LIVENESS_SCORE:
        return "LIVENESS_INCONCLUSIVE"
    return None


def _challenge_text() -> str:
    digits = [secrets.randbelow(10) for _ in range(4)]
    spoken_code = " ".join(DIGIT_WORDS[digit] for digit in digits)
    return f"{CHALLENGE_PREFIX} {spoken_code}"


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "ok", "service": "CHAABI FastAPI hub"}


@app.post("/api/accounts/signup", response_model=SessionResponse)
def signup(credentials: CredentialsRequest, response: Response) -> SessionResponse:
    user_id = _clean_user_id(credentials.user_id)
    now = int(time.time())
    salt = secrets.token_bytes(16)
    raw_token, token_hash, idle_expires_at, absolute_expires_at = (
        _new_session_values(now)
    )
    try:
        create_account_and_session(
            user_id,
            _password_digest(credentials.password, salt),
            salt.hex(),
            token_hash,
            now,
            idle_expires_at,
            absolute_expires_at,
        )
    except AccountAlreadyExistsError as exc:
        raise HTTPException(status_code=409, detail="That user ID already exists.") from exc
    except ActiveUserConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _set_session_cookie(response, raw_token)
    session = {
        "user_id": user_id,
        "idle_expires_at": idle_expires_at,
        "absolute_expires_at": absolute_expires_at,
    }
    logger.info("Local account created for user_id=%s", user_id)
    return _session_response(session)


@app.post("/api/accounts/login", response_model=SessionResponse)
def login(
    credentials: CredentialsRequest, request: Request, response: Response
) -> SessionResponse:
    user_id = _clean_user_id(credentials.user_id)
    authentication_key = _authentication_key(request, user_id)
    _enforce_credential_limit(authentication_key)
    stored = load_account_credentials(user_id)
    supplied_digest = ""
    if stored is not None:
        stored_digest, salt_hex = stored
        try:
            supplied_digest = _password_digest(credentials.password, bytes.fromhex(salt_hex))
        except ValueError:
            supplied_digest = ""
    else:
        stored_digest = secrets.token_hex(32)
        _password_digest(credentials.password, b"\x00" * 16)
    if not secrets.compare_digest(supplied_digest, stored_digest):
        credential_failures.setdefault(authentication_key, []).append(time.time())
        raise HTTPException(status_code=401, detail="Invalid user ID or password.")

    now = int(time.time())
    raw_token, token_hash, idle_expires_at, absolute_expires_at = (
        _new_session_values(now)
    )
    try:
        start_device_session(
            user_id,
            token_hash,
            now,
            idle_expires_at,
            absolute_expires_at,
        )
    except ActiveUserConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _set_session_cookie(response, raw_token)
    credential_failures.pop(authentication_key, None)
    session = {
        "user_id": user_id,
        "idle_expires_at": idle_expires_at,
        "absolute_expires_at": absolute_expires_at,
    }
    logger.info("Local account session started for user_id=%s", user_id)
    return _session_response(session)


@app.get("/api/session", response_model=SessionResponse)
def get_account_session(request: Request) -> SessionResponse:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_token:
        return SessionResponse(authenticated=False)
    session = resolve_device_session(
        _token_hash(raw_token),
        int(time.time()),
        idle_ttl_seconds=ACCOUNT_SESSION_IDLE_TTL_SECONDS,
        touch=True,
    )
    if session is None:
        return SessionResponse(authenticated=False)
    request.state.session_expires_at = int(session["idle_expires_at"])
    return _session_response(session)


@app.post("/api/accounts/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    raw_token = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_token:
        end_device_session(_token_hash(raw_token))
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


@app.get("/api/config", response_model=ConfigResponse)
def get_config(request: Request) -> ConfigResponse:
    _require_account_session(request)
    return ConfigResponse(
        enrollment_prompt=ENROLLMENT_PROMPT,
        enrollment_prompts=list(ENROLLMENT_PROMPTS),
        enrollment_recordings=ENROLLMENT_RECORDINGS,
        required_genuine_points=required_feature_count(),
        preferred_sample_rate=48_000,
    )


@app.get("/api/challenge", response_model=ChallengeResponse)
def get_challenge(request: Request) -> ChallengeResponse:
    user_id = _require_account_session(request)
    _cleanup_challenges()
    challenge_id = str(uuid.uuid4())
    text = _challenge_text()
    challenge_sessions[challenge_id] = {
        "text": text,
        "created_at": time.time(),
        "user_id": user_id,
    }
    return ChallengeResponse(
        challenge_id=challenge_id,
        text=text,
        expires_in_seconds=CHALLENGE_TTL_SECONDS,
    )


@app.post("/voice/enroll", response_model=EnrollResponse)
async def enroll(
    request: Request,
    replace_existing: bool = Form(False),
    audio_1: UploadFile = File(...),
    audio_2: UploadFile = File(...),
    audio_3: UploadFile = File(...),
) -> EnrollResponse:
    clean_user_id = _require_account_session(request)
    uploads = (audio_1, audio_2, audio_3)
    dsp_results: list[dict[str, Any]] = []
    speaker_embeddings: list[list[float]] = []

    for index, upload in enumerate(uploads, start=1):
        audio_bytes = await _read_audio_upload(upload)
        try:
            result = process_audio_buffer(audio_bytes, content_type=_content_type(upload))
        except AudioProcessingError as exc:
            logger.warning("Enrollment audio %d rejected: %s", index, exc)
            raise HTTPException(
                status_code=422,
                detail=f"Enrollment recording {index} is invalid or unsupported.",
            ) from exc

        reason = _quality_reason(result, require_liveness=True)
        if reason:
            return EnrollResponse(
                enrolled=False,
                user_id=clean_user_id,
                reason=f"RECORDING_{index}_{reason}",
                stable_bin_count=0,
                required_genuine_points=required_feature_count(),
            )
        dsp_results.append(result)
        try:
            speaker_embeddings.append(
                extract_speaker_embedding(
                    audio_bytes, content_type=_content_type(upload)
                )
            )
        except AudioProcessingError as exc:
            return EnrollResponse(
                enrolled=False,
                user_id=clean_user_id,
                reason=f"RECORDING_{index}_SPEAKER_FEATURES_UNAVAILABLE",
                stable_bin_count=0,
                required_genuine_points=required_feature_count(),
            )

    stable_bins = stable_formant_bins_from_dsp(
        dsp_results, minimum_recordings=ENROLLMENT_MINIMUM_SUPPORT
    )
    required = required_feature_count()
    if len(stable_bins) < required:
        return EnrollResponse(
            enrolled=False,
            user_id=clean_user_id,
            reason="INSUFFICIENT_STABLE_FORMANT_BINS",
            stable_bin_count=len(stable_bins),
            required_genuine_points=required,
        )

    try:
        speaker_profile = build_speaker_profile(speaker_embeddings)
    except SpeakerVerificationError:
        return EnrollResponse(
            enrolled=False,
            user_id=clean_user_id,
            reason="INCONSISTENT_ENROLLMENT_VOICE",
            stable_bin_count=len(stable_bins),
            required_genuine_points=required,
        )

    vault = generate_vault_from_bins(stable_bins[:required])
    vault["speaker_profile"] = speaker_profile
    try:
        save_vault(
            clean_user_id,
            vault,
            DSP_VERSION,
            int(time.time()),
            replace_existing=replace_existing,
        )
    except VaultAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "An enrollment already exists for this user. "
                "Enable explicit re-enrollment to replace it."
            ),
        ) from exc
    return EnrollResponse(
        enrolled=True,
        user_id=clean_user_id,
        reason="ENROLLMENT_SUCCESSFUL",
        stable_bin_count=len(stable_bins),
        required_genuine_points=required,
        vault_points=len(vault["points"]),
        genuine_points=int(vault["coefficient_count"]),
        speaker_threshold=float(speaker_profile["threshold"]),
        enrollment_voice_consistency=float(
            speaker_profile["enrollment_min_similarity"]
        ),
    )


@app.post("/voice/authenticate", response_model=AuthResponse)
async def authenticate(
    request: Request,
    challenge_id: str = Form(...),
    audio: UploadFile = File(...),
) -> AuthResponse:
    clean_user_id = _require_account_session(request)
    authentication_key = _authentication_key(request, clean_user_id)
    _enforce_authentication_limit(authentication_key)
    _cleanup_challenges()

    session = challenge_sessions.pop(challenge_id, None)
    if session is None or session.get("user_id") != clean_user_id:
        _record_authentication_failure(authentication_key, "INVALID_CHALLENGE")
        raise HTTPException(
            status_code=400,
            detail="The authentication request is invalid or expired.",
        )

    vault = load_vault(clean_user_id)
    if vault is None:
        _record_authentication_failure(authentication_key, "AUTHENTICATION_UNAVAILABLE")
        raise HTTPException(
            status_code=401,
            detail="Authentication could not be completed.",
        )

    audio_bytes = await _read_audio_upload(audio)
    try:
        dsp_result = process_audio_buffer(audio_bytes, content_type=_content_type(audio))
    except AudioProcessingError as exc:
        logger.warning("Authentication audio rejected: %s", exc)
        _record_authentication_failure(authentication_key, "INVALID_AUDIO")
        raise HTTPException(
            status_code=422, detail="Authentication audio is invalid or unsupported."
        ) from exc

    quality_reason = _quality_reason(dsp_result, require_liveness=True)
    required = int(vault["coefficient_count"])
    if quality_reason:
        _record_authentication_failure(authentication_key, quality_reason)
        return AuthResponse(
            authenticated=False,
            message="Please record the challenge again.",
            reason=quality_reason,
            dsp=dsp_result,
            crypto=CryptoResult(
                vault_unlocked=False,
                matched_points=0,
                required_points=required,
                error=quality_reason,
            ),
        )

    try:
        transcript = transcribe_english(audio_bytes)
    except SarvamError as exc:
        logger.warning("Sarvam STT unavailable: %s", exc)
        raise HTTPException(
            status_code=502, detail="The transcription service is temporarily unavailable."
        ) from exc

    prompt = str(session["text"])
    challenge_matched = challenge_matches_transcript(prompt, transcript)
    if (
        not challenge_matched
        and challenge_digits_match(prompt, transcript)
        and os.getenv("CHAABI_USE_LLM_INTENT", "false").lower() == "true"
    ):
        try:
            challenge_matched = verify_intent(prompt, transcript)
        except SarvamError as exc:
            logger.warning("Sarvam intent fallback unavailable: %s", exc)

    if not challenge_matched:
        _record_authentication_failure(authentication_key, "CHALLENGE_MISMATCH")
        return AuthResponse(
            authenticated=False,
            message="The spoken phrase did not match the active challenge.",
            reason="CHALLENGE_MISMATCH",
            transcript=transcript,
            challenge_matched=False,
            dsp=dsp_result,
            crypto=CryptoResult(
                vault_unlocked=False,
                matched_points=0,
                required_points=required,
                error="Challenge verification failed before vault recovery.",
            ),
        )

    speaker_profile = vault.get("speaker_profile")
    if (
        not isinstance(speaker_profile, dict)
        or speaker_profile.get("version") != PROFILE_VERSION
    ):
        _record_authentication_failure(authentication_key, "REENROLLMENT_REQUIRED")
        return AuthResponse(
            authenticated=False,
            message="This enrollment predates speaker verification. Please enroll again.",
            reason="REENROLLMENT_REQUIRED",
            transcript=transcript,
            challenge_matched=True,
            dsp=dsp_result,
            speaker=SpeakerResult(
                matched=False,
                error="Stored enrollment has no compatible multi-template voiceprint.",
            ),
            crypto=CryptoResult(
                vault_unlocked=False,
                matched_points=0,
                required_points=required,
                error="Speaker verification is required before vault recovery.",
            ),
        )

    try:
        live_embedding = extract_speaker_embedding(
            audio_bytes, content_type=_content_type(audio)
        )
        (
            speaker_matched,
            similarity,
            speaker_threshold,
            template_similarities,
        ) = compare_speaker(live_embedding, speaker_profile)
    except (AudioProcessingError, SpeakerVerificationError) as exc:
        _record_authentication_failure(
            authentication_key, "SPEAKER_FEATURES_UNAVAILABLE"
        )
        return AuthResponse(
            authenticated=False,
            message="Speaker comparison could not be completed.",
            reason="SPEAKER_FEATURES_UNAVAILABLE",
            transcript=transcript,
            challenge_matched=True,
            dsp=dsp_result,
            speaker=SpeakerResult(matched=False, error=str(exc)),
            crypto=CryptoResult(
                vault_unlocked=False,
                matched_points=0,
                required_points=required,
                error="Speaker verification failed before vault recovery.",
            ),
        )

    if not speaker_matched:
        _record_authentication_failure(authentication_key, "SPEAKER_MISMATCH")
        return AuthResponse(
            authenticated=False,
            message="The speaker does not match the enrolled voice profile.",
            reason="SPEAKER_MISMATCH",
            transcript=transcript,
            challenge_matched=True,
            dsp=dsp_result,
            speaker=SpeakerResult(
                matched=False,
                similarity=similarity,
                threshold=speaker_threshold,
                template_similarities=template_similarities,
            ),
            crypto=CryptoResult(
                vault_unlocked=False,
                matched_points=0,
                required_points=required,
                error="Speaker similarity was below the enrolled threshold.",
            ),
        )

    try:
        plaintext, matched_points = unlock_vault_with_details(
            formant_values_from_dsp(dsp_result), vault
        )
    except VaultAuthenticationError as exc:
        _record_authentication_failure(authentication_key, "VOICE_MISMATCH")
        return AuthResponse(
            authenticated=False,
            message="The voice features did not unlock the enrolled vault.",
            reason="VOICE_MISMATCH",
            transcript=transcript,
            challenge_matched=True,
            dsp=dsp_result,
            speaker=SpeakerResult(
                matched=True,
                similarity=similarity,
                threshold=speaker_threshold,
                template_similarities=template_similarities,
            ),
            crypto=CryptoResult(
                vault_unlocked=False,
                matched_points=0,
                required_points=required,
                error=str(exc),
            ),
        )

    logger.info(
        "Authentication succeeded for user_id=%s; payload_length=%d",
        clean_user_id,
        len(plaintext),
    )
    authentication_failures.pop(authentication_key, None)
    return AuthResponse(
        authenticated=True,
        message="Voice authentication successful.",
        reason="AUTHENTICATION_SUCCESSFUL",
        transcript=transcript,
        challenge_matched=True,
        dsp=dsp_result,
        speaker=SpeakerResult(
            matched=True,
            similarity=similarity,
            threshold=speaker_threshold,
            template_similarities=template_similarities,
        ),
        crypto=CryptoResult(
            vault_unlocked=True,
            matched_points=matched_points,
            required_points=required,
            confidence=round(min(matched_points / required, 1.0) * 100.0, 1),
        ),
    )
