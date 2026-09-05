"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import ConsoleHeader from "./ConsoleHeader";
import ChallengePanel from "./ChallengePanel";
import CapturePanel from "./CapturePanel";
import AuditLogPanel from "./AuditLogPanel";
import DemoControls from "./DemoControls";
import VerificationChecklist from "./VerificationChecklist";
import type {
  AuthResponse,
  AuditEntry,
  CheckStatus,
  EventTag,
  Phase,
  Readout,
  VerificationCheck,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_CHAABI_API_URL ?? "http://localhost:8000";
const RECORD_MS = 4000;

type ConsoleState = "IDLE" | "RECORDING" | "PROCESSING" | "SUCCESS" | "DENIED";
type Workflow = "enroll" | "authenticate";

type ConfigResponse = {
  enrollment_prompt: string;
  enrollment_prompts: string[];
  enrollment_recordings: number;
  required_genuine_points: number;
  preferred_sample_rate: number;
};

type ChallengeResponse = {
  challenge_id: string;
  text: string;
  expires_in_seconds: number;
};

type SessionResponse = {
  authenticated: boolean;
  user_id: string | null;
  expires_in_seconds: number;
  absolute_expires_in_seconds: number;
  has_voice_enrollment: boolean;
};

type EnrollResponse = {
  enrolled: boolean;
  user_id: string;
  reason: string;
  stable_bin_count: number;
  required_genuine_points: number;
  vault_points: number;
  genuine_points: number;
  speaker_threshold: number | null;
  enrollment_voice_consistency: number | null;
};

type DeviceCheck = {
  status: CheckStatus;
  detail: string;
};

const DEFAULT_CONFIG: ConfigResponse = {
  enrollment_prompt: "Please say access code one two three",
  enrollment_prompts: [
    "Please say access code one two three",
    "Please say access code four five six",
    "Please say access code seven eight nine",
  ],
  enrollment_recordings: 3,
  required_genuine_points: 18,
  preferred_sample_rate: 48000,
};

const INITIAL_DEVICE_CHECK: DeviceCheck = {
  status: "pending",
  detail: "Waiting for the automatic browser-session check.",
};

const PHASE_MAP: Record<ConsoleState, Phase> = {
  IDLE: "idle",
  RECORDING: "listening",
  PROCESSING: "analyzing",
  SUCCESS: "verified",
  DENIED: "denied",
};

const DEVICE_CHECK_ID = "device";

function initialChecks(workflow: Workflow, deviceCheck: DeviceCheck): VerificationCheck[] {
  if (workflow === "enroll") {
    return [
      { id: DEVICE_CHECK_ID, label: "Microphone and browser audio", ...deviceCheck },
      { id: "capture", label: "Enrollment recordings captured", status: "pending" },
      { id: "quality", label: "Speech quality and passive liveness", status: "pending" },
      { id: "formants", label: "Stable formant features", status: "pending" },
      { id: "speaker", label: "Enrollment voice consistency", status: "pending" },
      { id: "vault", label: "Cryptographic vault created", status: "pending" },
    ];
  }
  return [
    { id: DEVICE_CHECK_ID, label: "Microphone and browser audio", ...deviceCheck },
    { id: "capture", label: "Challenge audio captured", status: "pending" },
    { id: "speech", label: "Speech detected", status: "pending" },
    { id: "clipping", label: "Audio is not clipped", status: "pending" },
    { id: "liveness", label: "Passive replay check", status: "pending" },
    { id: "challenge", label: "One-time phrase matched", status: "pending" },
    { id: "speaker", label: "Speaker similarity check", status: "pending" },
    { id: "vault", label: "Cryptographic vault unlocked", status: "pending" },
    { id: "access", label: "Access decision", status: "pending" },
  ];
}

function phaseCopy(
  state: ConsoleState,
  workflow: Workflow,
  enrollmentCount: number,
  requiredRecordings: number
): { headline: string; subline: string } {
  if (state === "RECORDING") {
    return {
      headline: "Listening…",
      subline: "Speak the displayed phrase clearly and keep a consistent distance from the microphone.",
    };
  }
  if (state === "PROCESSING") {
    return {
      headline: workflow === "enroll" ? "Building voice profile…" : "Authenticating…",
      subline: "Running acoustic DSP, challenge verification, liveness checks, and fuzzy-vault recovery.",
    };
  }
  if (state === "SUCCESS") {
    return workflow === "enroll"
      ? { headline: "Enrollment complete", subline: "Stable acoustic features were sealed in the persistent vault." }
      : { headline: "Access granted", subline: "The challenge, acoustic features, and liveness checks passed." };
  }
  if (state === "DENIED") {
    return { headline: "Request not completed", subline: "See the audit log for the exact reason and try again." };
  }
  if (workflow === "enroll") {
    return {
      headline: `Enrollment recording ${Math.min(enrollmentCount + 1, requiredRecordings)} of ${requiredRecordings}`,
      subline: "Three recordings let CHAABI retain repeatable formant bins and reject one-off noise.",
    };
  }
  return {
    headline: "Ready to authenticate",
    subline: "Read the one-time challenge aloud. The recording window is four seconds.",
  };
}

function formatTime() {
  return new Date().toLocaleTimeString("en-GB", { hour12: false });
}

function computePeakDeviation(dataArray: Uint8Array): number {
  let peak = 0;
  for (const value of dataArray) {
    peak = Math.max(peak, Math.abs(value - 128) / 128);
  }
  return peak;
}

function enrollmentPrompt(config: ConfigResponse, recordingIndex: number): string {
  return config.enrollment_prompts[recordingIndex] ?? config.enrollment_prompt;
}

async function responseError(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((item) =>
          typeof item === "object" && item && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item)
        )
        .join("; ");
    }
  } catch {
    // Fall through to the HTTP status.
  }
  return `Request failed with HTTP ${response.status}`;
}

export default function AcousticConsole() {
  const [sessionStatus, setSessionStatus] = useState<"loading" | "authenticated" | "unauthenticated">("loading");
  const [sessionUser, setSessionUser] = useState<string | null>(null);
  const [authMode, setAuthMode] = useState<"login" | "signup">("login");
  const [authUserId, setAuthUserId] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [state, setState] = useState<ConsoleState>("IDLE");
  const [workflow, setWorkflow] = useState<Workflow>("enroll");
  const [userId, setUserId] = useState("");
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [config, setConfig] = useState<ConfigResponse>(DEFAULT_CONFIG);
  const [challenge, setChallenge] = useState<string>(DEFAULT_CONFIG.enrollment_prompt);
  const [challengeId, setChallengeId] = useState<string | null>(null);
  const [enrollmentRecordings, setEnrollmentRecordings] = useState<Blob[]>([]);
  const [log, setLog] = useState<AuditEntry[]>([]);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [readout, setReadout] = useState<Readout>({
    peak: "—",
    sampleRate: "—",
    frames: "—",
  });
  const [deviceLabel, setDeviceLabel] = useState("MIC · waiting");
  const [checks, setChecks] = useState<VerificationCheck[]>(() =>
    initialChecks("enroll", INITIAL_DEVICE_CHECK)
  );
  const [backendUp, setBackendUp] = useState(false);
  const [lastRecordingUrl, setLastRecordingUrl] = useState<string | null>(null);
  const [accent, setAccent] = useState("#2dd4bf");
  const [scanSpeed, setScanSpeed] = useState(1);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const pcmChunksRef = useRef<Float32Array[]>([]);
  const animationFrameRef = useRef<number | null>(null);
  const readoutIntervalRef = useRef<number | null>(null);
  const recordingTimeoutRef = useRef<number | null>(null);
  const peakRef = useRef(0);
  const scanSpeedRef = useRef(scanSpeed);
  const recordingWorkflowRef = useRef<Workflow>("enroll");
  const initializedRef = useRef(false);
  const lastRecordingUrlRef = useRef<string | null>(null);
  const deviceProbeRunningRef = useRef(false);
  const captureActiveRef = useRef(false);
  const deviceCheckRef = useRef<DeviceCheck>(INITIAL_DEVICE_CHECK);
  const sessionUserRef = useRef<string | null>(null);
  const sessionTimerRef = useRef<number | null>(null);

  const appendLog = (tag: EventTag, text: string, meta?: string) => {
    setLog((previous) => [
      { id: crypto.randomUUID(), time: formatTime(), tag, text, meta },
      ...previous,
    ]);
  };

  function armSessionTimer(seconds: number) {
    if (sessionTimerRef.current !== null) window.clearTimeout(sessionTimerRef.current);
    sessionTimerRef.current = window.setTimeout(
      () => expireLocalSession("Your session expired due to inactivity. Please log in again."),
      Math.max(1, seconds) * 1000
    );
  }

  function beginLocalSession(data: SessionResponse) {
    if (!data.authenticated || !data.user_id) return;
    sessionUserRef.current = data.user_id;
    setSessionUser(data.user_id);
    setUserId(data.user_id);
    setSessionStatus("authenticated");
    setAuthPassword("");
    setAuthError("");
    armSessionTimer(data.expires_in_seconds);
  }

  function expireLocalSession(message: string) {
    stopCapture();
    sessionUserRef.current = null;
    initializedRef.current = false;
    setSessionUser(null);
    setUserId("");
    setSessionStatus("unauthenticated");
    setAuthPassword("");
    setAuthError(message);
    setChallengeId(null);
    setEnrollmentRecordings([]);
    setState("IDLE");
  }

  async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
    const response = await fetch(input, { ...init, credentials: "include" });
    const remaining = Number(response.headers.get("X-Session-Expires-In"));
    if (Number.isFinite(remaining) && remaining > 0) armSessionTimer(remaining);
    if (response.status === 401 && sessionUserRef.current) {
      expireLocalSession("Your session is unavailable or expired. Please log in again.");
    }
    return response;
  }

  async function restoreSession() {
    try {
      const response = await fetch(`${API_BASE}/api/session`, {
        credentials: "include",
        cache: "no-store",
      });
      if (!response.ok) throw new Error(await responseError(response));
      const data = (await response.json()) as SessionResponse;
      if (data.authenticated) beginLocalSession(data);
      else setSessionStatus("unauthenticated");
    } catch (error) {
      setBackendUp(false);
      setSessionStatus("unauthenticated");
      setAuthError(error instanceof Error ? error.message : "Backend is unreachable.");
    }
  }

  async function submitCredentials() {
    setAuthBusy(true);
    setAuthError("");
    try {
      const response = await fetch(`${API_BASE}/api/accounts/${authMode}`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: authUserId.trim(), password: authPassword }),
      });
      if (!response.ok) throw new Error(await responseError(response));
      beginLocalSession((await response.json()) as SessionResponse);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Account authentication failed.");
    } finally {
      setAuthBusy(false);
    }
  }

  async function logout() {
    if (state === "RECORDING" || state === "PROCESSING") return;
    try {
      await fetch(`${API_BASE}/api/accounts/logout`, {
        method: "POST",
        credentials: "include",
      });
    } finally {
      expireLocalSession("");
      setAuthUserId("");
    }
  }

  useEffect(() => {
    scanSpeedRef.current = scanSpeed;
  }, [scanSpeed]);

  useEffect(() => {
    const restoreTimer = window.setTimeout(() => void restoreSession(), 0);

    const handleDeviceChange = () => {
      if (!sessionUserRef.current) return;
      setDeviceReadiness({
        status: "running",
        detail: "Audio device changed; checking the active microphone again.",
      });
      appendLog("DSP", "Audio device change detected", "running microphone readiness check");
      void runDeviceReadinessCheck("Audio device changed");
    };
    navigator.mediaDevices?.addEventListener("devicechange", handleDeviceChange);
    return () => {
      window.clearTimeout(restoreTimer);
      navigator.mediaDevices?.removeEventListener("devicechange", handleDeviceChange);
      stopCapture();
      if (lastRecordingUrlRef.current) {
        URL.revokeObjectURL(lastRecordingUrlRef.current);
      }
      if (sessionTimerRef.current !== null) window.clearTimeout(sessionTimerRef.current);
    };
    // Initialization and cleanup intentionally run only on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (sessionStatus !== "authenticated" || initializedRef.current) return;
    initializedRef.current = true;
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.width = canvas.clientWidth;
      canvas.height = 300;
      drawIdleGrid();
    }
    void initialize();
    void runDeviceReadinessCheck("Authenticated browser session started");
    // Initialization runs once for each authenticated account session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionStatus]);

  function updateCheck(id: string, status: CheckStatus, detail?: string) {
    setChecks((previous) =>
      previous.map((check) =>
        check.id === id ? { ...check, status, detail } : check
      )
    );
  }

  function setDeviceReadiness(next: DeviceCheck) {
    deviceCheckRef.current = next;
    setChecks((previous) =>
      previous.map((check) =>
        check.id === DEVICE_CHECK_ID ? { ...check, ...next } : check
      )
    );
  }

  function resetChecks(nextWorkflow: Workflow) {
    setChecks(initialChecks(nextWorkflow, deviceCheckRef.current));
  }

  async function runDeviceReadinessCheck(trigger: string) {
    if (deviceProbeRunningRef.current) return;
    if (captureActiveRef.current) {
      setDeviceReadiness({
        status: "running",
        detail: "The active recording will validate the newly selected microphone.",
      });
      return;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setDeviceReadiness({ status: "failed", detail: "Browser microphone capture is unavailable." });
      return;
    }

    deviceProbeRunningRef.current = true;
    setDeviceReadiness({ status: "running", detail: `${trigger}; requesting microphone settings.` });
    let probeStream: MediaStream | null = null;
    let probeContext: AudioContext | null = null;
    try {
      probeStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: { ideal: config.preferred_sample_rate },
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
      const SafariAudioContext = (
        window as typeof window & { webkitAudioContext?: typeof AudioContext }
      ).webkitAudioContext;
      const AudioContextConstructor = window.AudioContext ?? SafariAudioContext;
      if (!AudioContextConstructor) throw new Error("AudioContext is unavailable");
      probeContext = new AudioContextConstructor();

      const track = probeStream.getAudioTracks()[0];
      const settings = track?.getSettings();
      const rate = probeContext.sampleRate;
      const label = track?.label || "Microphone";
      const supportsLivenessBand = rate > 32_000;
      setDeviceLabel(`${label} · ${rate}Hz`);
      setReadout((previous) => ({ ...previous, sampleRate: String(rate) }));
      setDeviceReadiness({
        status: supportsLivenessBand ? "passed" : "failed",
        detail: supportsLivenessBand
          ? `${label} at ${rate} Hz; passive liveness frequency band is available.`
          : `${label} at ${rate} Hz; use a sample rate above 32 kHz for passive liveness.`,
      });
      appendLog(
        supportsLivenessBand ? "DSP" : "DENY",
        supportsLivenessBand ? "Microphone readiness check passed" : "Microphone sample rate is insufficient",
        `${trigger} · context ${rate}Hz · device ${settings?.sampleRate ?? "auto"}Hz`
      );
    } catch (error) {
      const message = error instanceof Error ? error.message : "Microphone readiness check failed";
      setDeviceReadiness({ status: "failed", detail: message });
      appendLog("DENY", "Automatic microphone readiness check failed", message);
    } finally {
      probeStream?.getTracks().forEach((track) => track.stop());
      if (probeContext && probeContext.state !== "closed") await probeContext.close();
      deviceProbeRunningRef.current = false;
    }
  }

  async function initialize() {
    try {
      const response = await apiFetch(`${API_BASE}/api/config`);
      if (!response.ok) throw new Error(await responseError(response));
      const data = (await response.json()) as ConfigResponse;
      setConfig(data);
      setChallenge(enrollmentPrompt(data, 0));
      setBackendUp(true);
      appendLog(
        "DSP",
        "Backend contract loaded",
        `${data.enrollment_recordings} enrollment recordings · ${data.required_genuine_points} genuine points`
      );
    } catch (error) {
      setBackendUp(false);
      appendLog("DENY", error instanceof Error ? error.message : "Backend is unreachable");
    }
  }

  async function fetchChallenge() {
    setChallengeId(null);
    try {
      const response = await apiFetch(
        `${API_BASE}/api/challenge`,
        { cache: "no-store" }
      );
      if (!response.ok) throw new Error(await responseError(response));
      const data = (await response.json()) as ChallengeResponse;
      setChallenge(data.text);
      setChallengeId(data.challenge_id);
      setBackendUp(true);
      appendLog("INTENT", "New one-time challenge issued", `expires in ${data.expires_in_seconds}s`);
    } catch (error) {
      setBackendUp(false);
      appendLog("DENY", error instanceof Error ? error.message : "Could not fetch a challenge");
    }
  }

  function chooseWorkflow(nextWorkflow: Workflow) {
    if (state === "RECORDING" || state === "PROCESSING") return;
    setWorkflow(nextWorkflow);
    setState("IDLE");
    setConfidence(null);
    resetChecks(nextWorkflow);
    if (nextWorkflow === "enroll") {
      setEnrollmentRecordings([]);
      setChallengeId(null);
      setChallenge(enrollmentPrompt(config, 0));
    } else {
      void fetchChallenge();
    }
  }

  function drawGrid(context: CanvasRenderingContext2D, width: number, height: number) {
    context.strokeStyle = "rgba(255,255,255,0.05)";
    context.lineWidth = 1;
    for (let x = 0; x <= width; x += width / 6) {
      context.beginPath();
      context.moveTo(x, 0);
      context.lineTo(x, height);
      context.stroke();
    }
    for (let y = 0; y <= height; y += height / 4) {
      context.beginPath();
      context.moveTo(0, y);
      context.lineTo(width, y);
      context.stroke();
    }
  }

  function drawIdleGrid() {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;
    context.fillStyle = "#0a0b0d";
    context.fillRect(0, 0, canvas.width, canvas.height);
    drawGrid(context, canvas.width, canvas.height);
  }

  function drawWaveform() {
    const canvas = canvasRef.current;
    const analyser = analyserRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !analyser || !context) return;

    const data = new Uint8Array(analyser.fftSize);
    const render = () => {
      analyser.getByteTimeDomainData(data);
      peakRef.current = computePeakDeviation(data);
      const alpha = Math.min(0.9, Math.max(0.12, 0.35 * scanSpeedRef.current));
      context.fillStyle = `rgba(10, 11, 13, ${alpha})`;
      context.fillRect(0, 0, canvas.width, canvas.height);
      drawGrid(context, canvas.width, canvas.height);
      context.lineWidth = 2;
      context.strokeStyle = accent;
      context.beginPath();
      const sliceWidth = canvas.width / data.length;
      for (let index = 0; index < data.length; index += 1) {
        const x = index * sliceWidth;
        const y = (data[index] / 128) * canvas.height / 2;
        if (index === 0) context.moveTo(x, y);
        else context.lineTo(x, y);
      }
      context.stroke();
      animationFrameRef.current = requestAnimationFrame(render);
    };
    render();
  }

  function encodeWav(samples: Float32Array, sampleRate: number): Blob {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const write = (offset: number, value: string) => {
      for (let index = 0; index < value.length; index += 1) {
        view.setUint8(offset + index, value.charCodeAt(index));
      }
    };
    write(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    write(8, "WAVE");
    write(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    write(36, "data");
    view.setUint32(40, samples.length * 2, true);
    for (let index = 0, offset = 44; index < samples.length; index += 1, offset += 2) {
      const sample = Math.max(-1, Math.min(1, samples[index]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    }
    return new Blob([view], { type: "audio/wav" });
  }

  function rememberRecording(recording: Blob) {
    if (lastRecordingUrlRef.current) {
      URL.revokeObjectURL(lastRecordingUrlRef.current);
    }
    const url = URL.createObjectURL(recording);
    lastRecordingUrlRef.current = url;
    setLastRecordingUrl(url);
  }

  function stopCapture() {
    if (recordingTimeoutRef.current !== null) {
      clearTimeout(recordingTimeoutRef.current);
      recordingTimeoutRef.current = null;
    }
    if (readoutIntervalRef.current !== null) {
      clearInterval(readoutIntervalRef.current);
      readoutIntervalRef.current = null;
    }
    if (animationFrameRef.current !== null) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    processorRef.current?.disconnect();
    analyserRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      void audioCtxRef.current.close();
    }
    processorRef.current = null;
    analyserRef.current = null;
    streamRef.current = null;
    audioCtxRef.current = null;
    captureActiveRef.current = false;
  }

  async function startRecording() {
    const cleanUserId = userId.trim();
    if (!cleanUserId) {
      appendLog("DENY", "Enter a user ID before recording.");
      return;
    }
    if (workflow === "authenticate" && !challengeId) {
      appendLog("DENY", "No active challenge. Request a new challenge.");
      return;
    }

    setState("RECORDING");
    setConfidence(null);
    resetChecks(workflow);
    updateCheck("capture", "running", "Recording from the active microphone.");
    recordingWorkflowRef.current = workflow;
    pcmChunksRef.current = [];
    captureActiveRef.current = true;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: { ideal: config.preferred_sample_rate },
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
      streamRef.current = stream;

      const SafariAudioContext = (
        window as typeof window & { webkitAudioContext?: typeof AudioContext }
      ).webkitAudioContext;
      const AudioContextConstructor = window.AudioContext ?? SafariAudioContext;
      if (!AudioContextConstructor) throw new Error("AudioContext is unavailable");
      const audioContext = new AudioContextConstructor();
      audioCtxRef.current = audioContext;

      const track = stream.getAudioTracks()[0];
      const settings = track?.getSettings();
      const rate = audioContext.sampleRate;
      setDeviceLabel(`${track?.label || "MIC"} · ${rate}Hz`);
      const supportsLivenessBand = rate > 32_000;
      setDeviceReadiness({
        status: supportsLivenessBand ? "passed" : "failed",
        detail: supportsLivenessBand
          ? `${track?.label || "Microphone"} at ${rate} Hz; active capture verified.`
          : `${track?.label || "Microphone"} at ${rate} Hz; passive liveness needs more than 32 kHz.`,
      });
      setReadout((previous) => ({ ...previous, sampleRate: String(rate), frames: "—" }));
      appendLog(
        workflow === "enroll" ? "ENROLL" : "CAPTURE",
        workflow === "enroll"
          ? `Capturing enrollment sample ${enrollmentRecordings.length + 1}/${config.enrollment_recordings}`
          : "Capturing one-time challenge",
        `${RECORD_MS / 1000}s · context ${rate}Hz · device ${settings?.sampleRate ?? "auto"}Hz`
      );

      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      analyserRef.current = analyser;
      source.connect(analyser);

      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      processor.onaudioprocess = (event) => {
        pcmChunksRef.current.push(new Float32Array(event.inputBuffer.getChannelData(0)));
      };
      const mutedOutput = audioContext.createGain();
      mutedOutput.gain.value = 0;
      source.connect(processor);
      processor.connect(mutedOutput);
      mutedOutput.connect(audioContext.destination);

      drawWaveform();
      readoutIntervalRef.current = window.setInterval(() => {
        const peak = peakRef.current;
        setReadout((previous) => ({
          ...previous,
          peak: peak > 0 ? (20 * Math.log10(peak)).toFixed(1) : "-inf",
        }));
      }, 200);
      recordingTimeoutRef.current = window.setTimeout(
        () => void finishRecording(rate),
        RECORD_MS
      );
    } catch (error) {
      stopCapture();
      setState("IDLE");
      updateCheck("capture", "failed", "The browser could not start microphone capture.");
      appendLog(
        "DENY",
        error instanceof Error ? error.message : "Microphone access was denied"
      );
    }
  }

  async function finishRecording(sampleRate: number) {
    if (state !== "RECORDING" && pcmChunksRef.current.length === 0) return;
    stopCapture();
    setState("PROCESSING");

    const totalLength = pcmChunksRef.current.reduce((sum, chunk) => sum + chunk.length, 0);
    if (totalLength === 0) {
      appendLog("DENY", "The browser returned an empty recording.");
      updateCheck("capture", "failed", "The browser returned no audio samples.");
      setState("DENIED");
      return;
    }

    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of pcmChunksRef.current) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }
    const audio = encodeWav(merged, sampleRate);
    rememberRecording(audio);
    updateCheck("capture", "passed", `${(totalLength / sampleRate).toFixed(1)} seconds captured at ${sampleRate} Hz.`);

    if (recordingWorkflowRef.current === "enroll") {
      const recordings = [...enrollmentRecordings, audio];
      setEnrollmentRecordings(recordings);
      if (recordings.length < config.enrollment_recordings) {
        setChallenge(enrollmentPrompt(config, recordings.length));
        updateCheck(
          "capture",
          "running",
          `${recordings.length}/${config.enrollment_recordings} recordings captured.`
        );
        appendLog("ENROLL", "Sample retained locally", `${recordings.length}/${config.enrollment_recordings} ready`);
        setState("IDLE");
        return;
      }
      await submitEnrollment(recordings);
    } else {
      await submitAuthentication(audio);
    }
  }

  async function submitEnrollment(recordings: Blob[]) {
    const formData = new FormData();
    formData.append("replace_existing", String(replaceExisting));
    recordings.forEach((recording, index) => {
      formData.append(`audio_${index + 1}`, recording, `enrollment-${index + 1}.wav`);
    });

    try {
      updateCheck("quality", "running", "Analyzing speech quality and replay indicators.");
      updateCheck("formants", "running", "Finding repeatable formant bins across recordings.");
      updateCheck("speaker", "running", "Comparing the three enrollment voiceprints.");
      updateCheck("vault", "running", "Waiting for validated acoustic features.");
      const response = await apiFetch(`${API_BASE}/voice/enroll`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error(await responseError(response));
      const data = (await response.json()) as EnrollResponse;
      if (!data.enrolled) {
        appendLog(
          "DENY",
          data.reason,
          `stable bins ${data.stable_bin_count}/${data.required_genuine_points}`
        );
        setEnrollmentRecordings([]);
        updateCheck("quality", data.reason.includes("RECORDING_") ? "failed" : "passed", data.reason);
        const stableFormantsAvailable =
          data.stable_bin_count >= data.required_genuine_points;
        updateCheck(
          "formants",
          stableFormantsAvailable
            ? "passed"
            : data.reason === "INSUFFICIENT_STABLE_FORMANT_BINS"
              ? "failed"
              : "skipped",
          `Stable bins ${data.stable_bin_count}/${data.required_genuine_points}.`
        );
        updateCheck(
          "speaker",
          data.reason === "INCONSISTENT_ENROLLMENT_VOICE" ? "failed" : "skipped",
          data.reason === "INCONSISTENT_ENROLLMENT_VOICE" ? data.reason : "Not reached."
        );
        updateCheck("vault", "skipped", "Enrollment checks did not all pass.");
        setState("DENIED");
        return;
      }

      appendLog(
        "GRANT",
        "Voice enrollment completed",
        `${data.genuine_points} genuine + ${data.vault_points - data.genuine_points} chaff points`
      );
      if (data.speaker_threshold !== null) {
        appendLog(
          "DSP",
          "Speaker voiceprint enrolled",
          `consistency ${data.enrollment_voice_consistency ?? "—"} · acceptance threshold ${data.speaker_threshold}`
        );
      }
      setConfidence(100);
      updateCheck("capture", "passed", `${recordings.length}/${config.enrollment_recordings} recordings received.`);
      updateCheck("quality", "passed", "All recordings passed quality and passive liveness checks.");
      updateCheck("formants", "passed", `${data.stable_bin_count} stable bins; ${data.required_genuine_points} required.`);
      updateCheck(
        "speaker",
        "passed",
        `Minimum enrollment similarity ${data.enrollment_voice_consistency ?? "available"}.`
      );
      updateCheck("vault", "passed", `${data.genuine_points} genuine points sealed with chaff.`);
      setState("SUCCESS");
      setEnrollmentRecordings([]);
      setChallenge(enrollmentPrompt(config, 0));
    } catch (error) {
      const message = error instanceof Error ? error.message : "Enrollment failed";
      appendLog("DENY", message);
      updateCheck("quality", "failed", message);
      updateCheck("formants", "skipped", "Backend processing did not complete.");
      updateCheck("speaker", "skipped", "Backend processing did not complete.");
      updateCheck("vault", "skipped", "Backend processing did not complete.");
      setEnrollmentRecordings([]);
      setState("DENIED");
    }
  }

  async function submitAuthentication(audio: Blob) {
    if (!challengeId) return;
    const formData = new FormData();
    formData.append("challenge_id", challengeId);
    formData.append("audio", audio, "challenge.wav");

    try {
      for (const id of ["speech", "clipping", "liveness"]) {
        updateCheck(id, "running", "Analyzing the captured waveform.");
      }
      const response = await apiFetch(`${API_BASE}/voice/authenticate`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error(await responseError(response));
      handleAuthentication((await response.json()) as AuthResponse);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Authentication failed";
      appendLog("DENY", message);
      for (const id of ["speech", "clipping", "liveness"]) {
        updateCheck(id, "failed", message);
      }
      for (const id of ["challenge", "speaker", "vault"]) {
        updateCheck(id, "skipped", "Authentication processing did not reach this check.");
      }
      updateCheck("access", "failed", message);
      setState("DENIED");
    } finally {
      setChallengeId(null);
    }
  }

  function handleAuthentication(data: AuthResponse) {
    const dsp = data.dsp;
    if (dsp) {
      const summary = dsp.formant_summary;
      setReadout({
        peak: dsp.audio_quality.peak > 0
          ? (20 * Math.log10(dsp.audio_quality.peak)).toFixed(1)
          : "-inf",
        sampleRate: String(dsp.audio_quality.sample_rate),
        frames: String(dsp.formant_frames.length),
      });
      appendLog(
        "DSP",
        `${dsp.formant_frames.length} formant frames extracted`,
        summary.f1_hz === null
          ? "summary unavailable"
          : `F1 ${summary.f1_hz} · F2 ${summary.f2_hz} · F3 ${summary.f3_hz} Hz`
      );
      appendLog(
        "DSP",
        dsp.is_replay_attack
          ? "High replay risk"
          : dsp.liveness_available
            ? "Passive liveness signal available"
            : "Passive liveness inconclusive",
        dsp.liveness_score === null ? undefined : `liveness score ${dsp.liveness_score}`
      );
      updateCheck(
        "speech",
        dsp.audio_quality.speech_detected ? "passed" : "failed",
        dsp.audio_quality.speech_detected ? `${dsp.formant_frames.length} voiced formant frames found.` : "No usable speech was detected."
      );
      updateCheck(
        "clipping",
        dsp.audio_quality.clipping_detected ? "failed" : "passed",
        dsp.audio_quality.clipping_detected ? "The signal exceeded the clipping limit." : `Peak amplitude ${dsp.audio_quality.peak}.`
      );
      const livenessPassed =
        dsp.liveness_available &&
        !dsp.is_replay_attack &&
        data.reason !== "LIVENESS_INCONCLUSIVE";
      updateCheck(
        "liveness",
        livenessPassed ? "passed" : "failed",
        dsp.liveness_score === null
          ? "Passive liveness could not be evaluated."
          : `Liveness score ${dsp.liveness_score}; ${dsp.is_replay_attack ? "replay risk detected" : "no high replay risk detected"}.`
      );
    } else {
      for (const id of ["speech", "clipping", "liveness"]) {
        updateCheck(id, "failed", "No DSP result was returned.");
      }
    }

    if (data.transcript !== null) {
      appendLog("STT", `Transcript: "${data.transcript}"`);
      appendLog(
        "INTENT",
        data.challenge_matched ? "Challenge matched exactly" : "Challenge mismatch"
      );
      updateCheck(
        "challenge",
        data.challenge_matched ? "passed" : "failed",
        data.challenge_matched ? `Transcript: “${data.transcript}”` : `Transcript did not match: “${data.transcript}”`
      );
    } else {
      updateCheck("challenge", "skipped", "Audio checks failed before transcription.");
    }

    if (data.speaker) {
      appendLog(
        data.speaker.matched ? "DSP" : "DENY",
        data.speaker.matched ? "Enrolled speaker matched" : "Speaker voiceprint mismatch",
        data.speaker.similarity === null
          ? data.speaker.error ?? undefined
          : `similarity ${data.speaker.similarity} · required ${data.speaker.threshold}`
      );
      if (data.speaker.similarity !== null) {
        setConfidence(Math.max(0, Math.min(100, data.speaker.similarity * 100)));
      }
      updateCheck(
        "speaker",
        data.speaker.matched ? "passed" : "failed",
        data.speaker.similarity === null
          ? data.speaker.error ?? "Speaker comparison was unavailable."
          : `Best-two average ${data.speaker.similarity}; required ${data.speaker.threshold}. Templates ${data.speaker.template_similarities.join(", ")}.`
      );
    } else {
      updateCheck(
        "speaker",
        "skipped",
        data.challenge_matched ? "Speaker result was unavailable." : "Phrase verification did not pass."
      );
    }

    if (data.crypto) {
      appendLog(
        data.crypto.vault_unlocked ? "GRANT" : "DENY",
        data.crypto.vault_unlocked ? "Fuzzy vault unlocked" : data.crypto.error ?? "Vault remained locked",
        `matched ${data.crypto.matched_points}/${data.crypto.required_points}`
      );
      if (!data.speaker) setConfidence(data.crypto.confidence);
      const vaultWasAttempted =
        data.crypto.vault_unlocked ||
        data.reason === "VOICE_MISMATCH" ||
        data.reason === "AUTHENTICATION_SUCCESSFUL";
      updateCheck(
        "vault",
        data.crypto.vault_unlocked ? "passed" : vaultWasAttempted ? "failed" : "skipped",
        data.crypto.vault_unlocked
          ? `Matched ${data.crypto.matched_points}/${data.crypto.required_points} required points.`
          : vaultWasAttempted
            ? data.crypto.error ?? "Vault recovery failed."
            : "An earlier authentication gate did not pass."
      );
    } else {
      updateCheck("vault", "skipped", "No vault result was returned.");
    }
    if (!data.authenticated && !data.crypto) appendLog("DENY", data.reason);
    updateCheck(
      "access",
      data.authenticated ? "passed" : "failed",
      data.authenticated ? "All required gates passed." : data.reason
    );
    setState(data.authenticated ? "SUCCESS" : "DENIED");
  }

  function reset() {
    stopCapture();
    setState("IDLE");
    setConfidence(null);
    resetChecks(workflow);
    setReadout({ peak: "—", sampleRate: "—", frames: "—" });
    drawIdleGrid();
    if (workflow === "enroll") {
      setEnrollmentRecordings([]);
      setChallenge(enrollmentPrompt(config, 0));
    } else {
      void fetchChallenge();
    }
  }

  if (sessionStatus === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[var(--bg)] p-8 text-[var(--ink)]">
        <p className="font-mono text-xs tracking-[0.18em] text-[var(--muted)]">CHECKING DEVICE SESSION…</p>
      </main>
    );
  }

  if (sessionStatus === "unauthenticated") {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[var(--bg)] p-6 text-[var(--ink)]">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void submitCredentials();
          }}
          className="w-full max-w-md rounded-[18px] border border-[var(--border)] bg-[var(--surface)] p-8"
        >
          <p className="font-mono text-[10px] tracking-[0.2em] text-[var(--signal)]">CHAABI EDGE ACCESS</p>
          <h1 className="mt-3 text-3xl font-semibold">{authMode === "login" ? "Log in" : "Create account"}</h1>
          <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
            {authMode === "login"
              ? "Unlock this device session with your local credentials. Voice authentication remains a separate security gate."
              : "Create credentials stored only on this edge device, then enroll your voice profile."}
          </p>
          <label className="mt-7 flex flex-col gap-2">
            <span className="font-mono text-[10px] tracking-[0.14em] text-[var(--muted)]">USER ID</span>
            <input
              value={authUserId}
              onChange={(event) => setAuthUserId(event.target.value)}
              autoComplete="username"
              maxLength={64}
              required
              className="rounded-lg border border-[var(--border)] bg-black/20 px-3 py-3 font-mono text-sm outline-none focus:border-[var(--signal)]"
            />
          </label>
          <label className="mt-4 flex flex-col gap-2">
            <span className="font-mono text-[10px] tracking-[0.14em] text-[var(--muted)]">PASSWORD</span>
            <input
              type="password"
              value={authPassword}
              onChange={(event) => setAuthPassword(event.target.value)}
              autoComplete={authMode === "login" ? "current-password" : "new-password"}
              minLength={10}
              maxLength={128}
              required
              className="rounded-lg border border-[var(--border)] bg-black/20 px-3 py-3 font-mono text-sm outline-none focus:border-[var(--signal)]"
            />
          </label>
          {authError ? <p className="mt-4 text-sm text-red-300">{authError}</p> : null}
          <button
            type="submit"
            disabled={authBusy || !authUserId.trim() || authPassword.length < 10}
            className="mt-6 w-full rounded-lg bg-[var(--signal)] px-4 py-3 font-mono text-xs font-semibold tracking-[0.12em] text-[var(--bg)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {authBusy ? "PLEASE WAIT…" : authMode === "login" ? "LOG IN" : "SIGN UP"}
          </button>
          <button
            type="button"
            disabled={authBusy}
            onClick={() => {
              setAuthMode(authMode === "login" ? "signup" : "login");
              setAuthPassword("");
              setAuthError("");
            }}
            className="mt-4 w-full font-mono text-[10px] tracking-[0.12em] text-[var(--muted)] hover:text-[var(--ink)]"
          >
            {authMode === "login" ? "NEW USER? CREATE AN ACCOUNT" : "ALREADY REGISTERED? LOG IN"}
          </button>
        </form>
      </main>
    );
  }

  const copy = phaseCopy(
    state,
    workflow,
    enrollmentRecordings.length,
    config.enrollment_recordings
  );
  const busy = state === "RECORDING" || state === "PROCESSING";
  const captureLabel =
    workflow === "enroll"
      ? `RECORD ${Math.min(enrollmentRecordings.length + 1, config.enrollment_recordings)}/${config.enrollment_recordings}`
      : "VERIFY";

  return (
    <div
      className="min-h-screen p-8"
      style={{ "--signal": accent, background: "var(--bg)" } as CSSProperties}
    >
      <div className="mx-auto flex max-w-[1400px] flex-col gap-6">
        <ConsoleHeader
          sessionId={challengeId ?? (workflow === "enroll" ? "ENROLLMENT" : "—")}
          device={deviceLabel}
          linkUp={backendUp}
        />

        <section className="flex flex-wrap items-center gap-4 rounded-[14px] border border-[var(--border)] bg-[var(--surface)] px-5 py-4">
          <div className="min-w-[220px] flex-1">
            <span className="font-mono text-[10px] tracking-[0.14em] text-[var(--muted)]">SIGNED IN USER</span>
            <p className="mt-1 font-mono text-sm text-[var(--ink)]">{sessionUser}</p>
          </div>
          {workflow === "enroll" ? (
            <label className="flex items-center gap-2.5 font-mono text-[10px] tracking-[0.1em] text-[var(--muted)]">
              <input
                type="checkbox"
                checked={replaceExisting}
                onChange={(event) => setReplaceExisting(event.target.checked)}
                disabled={busy}
                className="size-4 accent-[var(--signal)]"
              />
              REPLACE MY EXISTING VOICE ENROLLMENT
            </label>
          ) : null}
          <div className="flex overflow-hidden rounded-lg border border-[var(--border)]">
            {(["enroll", "authenticate"] as Workflow[]).map((item) => (
              <button
                key={item}
                type="button"
                disabled={busy}
                onClick={() => chooseWorkflow(item)}
                className={`px-4 py-2.5 font-mono text-[10px] uppercase tracking-[0.12em] ${
                  workflow === item
                    ? "bg-[var(--signal)] text-[var(--bg)]"
                    : "text-[var(--muted)] hover:bg-white/[.05]"
                }`}
              >
                {item}
              </button>
            ))}
          </div>
          {workflow === "authenticate" ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => void fetchChallenge()}
              className="rounded-lg border border-[var(--border)] px-4 py-2.5 font-mono text-[10px] tracking-[0.12em] text-[var(--ink)] hover:bg-white/[.05]"
            >
              NEW CHALLENGE
            </button>
          ) : null}
          <button
            type="button"
            disabled={busy}
            onClick={() => void logout()}
            className="rounded-lg border border-[var(--border)] px-4 py-2.5 font-mono text-[10px] tracking-[0.12em] text-[var(--ink)] hover:bg-white/[.05] disabled:cursor-not-allowed disabled:opacity-50"
          >
            LOG OUT
          </button>
        </section>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_380px]">
          <div className="flex flex-col gap-6">
            <ChallengePanel
              phrase={challenge}
              label={
                workflow === "enroll"
                  ? `SAY THIS FOR RECORDING ${Math.min(enrollmentRecordings.length + 1, config.enrollment_recordings)} OF ${config.enrollment_recordings}`
                  : "READ THIS ONE-TIME PHRASE ALOUD"
              }
            />
            {lastRecordingUrl ? (
              <section className="flex flex-wrap items-center gap-4 rounded-[14px] border border-[var(--border)] bg-[var(--surface)] px-5 py-4">
                <div className="min-w-[220px] flex-1">
                  <div className="font-mono text-[10px] tracking-[0.14em] text-[var(--muted)]">
                    LAST BROWSER RECORDING
                  </div>
                  <p className="mt-1 text-[12px] text-[var(--muted)]">
                    Play this locally to confirm the microphone captured your complete phrase clearly.
                  </p>
                </div>
                <audio controls preload="metadata" src={lastRecordingUrl} className="h-10 max-w-full" />
              </section>
            ) : null}
            <CapturePanel
              phase={PHASE_MAP[state]}
              headline={copy.headline}
              subline={copy.subline}
              readout={readout}
              confidence={confidence}
              canvasRef={canvasRef}
              onCapture={() => void startRecording()}
              onReset={reset}
              captureLabel={captureLabel}
              disabled={
                !backendUp ||
                !userId.trim() ||
                (workflow === "authenticate" && !challengeId)
              }
            />
            <DemoControls
              accent={accent}
              onAccentChange={setAccent}
              scanSpeed={scanSpeed}
              onScanSpeedChange={setScanSpeed}
            />
          </div>
          <div className="flex min-h-0 flex-col gap-6">
            <VerificationChecklist
              title={workflow === "enroll" ? "ENROLLMENT CHECKS" : "AUTHENTICATION CHECKS"}
              checks={checks}
            />
            <AuditLogPanel
              entries={log}
              footer="LOCAL DIAGNOSTIC EVENT STREAM"
            />
          </div>
        </div>
      </div>
    </div>
  );
}
