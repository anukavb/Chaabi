"use client";

import { useEffect, useRef, useState } from "react";
import ConsoleHeader from "./ConsoleHeader";
import ChallengePanel from "./ChallengePanel";
import CapturePanel from "./CapturePanel";
import AuditLogPanel from "./AuditLogPanel";
import DemoControls from "./DemoControls";
import type { Phase, AuditEntry, EventTag, Readout } from "./types";

const API_BASE = "http://localhost:8000";
const RECORD_MS = 4000;
const TARGET_SAMPLE_RATE = 16000;
const DEVICE_LABEL = "MIC-01 · 48kHz";

// true = fake local data, no backend needed. false = call the real backend.
const MOCK_MODE = true;
type MockScenario = "success" | "replay" | "imposter" | "wrong_phrase";
// Fallback used only when DemoControls' forceVerdict is "auto".
const MOCK_SCENARIO: MockScenario = "success";

type ConsoleState = "IDLE" | "RECORDING" | "PROCESSING" | "SUCCESS" | "DENIED";
type Verdict = "auto" | "grant" | "deny";

const PHASE_MAP: Record<ConsoleState, Phase> = {
  IDLE: "idle",
  RECORDING: "listening",
  PROCESSING: "analyzing",
  SUCCESS: "verified",
  DENIED: "denied",
};

interface VerifyResponse {
  status: "SUCCESS" | "DENIED";
  dsp?: { is_replay_attack: boolean; F1?: number; F2?: number; F3?: number };
  sarvam?: { transcript?: string; intent_valid?: boolean };
  crypto?: {
    vault_unlocked: boolean;
    payload?: string;
    error?: string;
    confidence?: number; // 0–100 scale
  };
}

function phaseCopy(state: ConsoleState): { headline: string; subline: string } {
  switch (state) {
    case "RECORDING":
      return {
        headline: "Listening…",
        subline: "Recording your voice — read the challenge phrase clearly into the microphone.",
      };
    case "PROCESSING":
      return {
        headline: "Analyzing…",
        subline: "Extracting formants and verifying against Sarvam AI and the sealed vault.",
      };
    case "SUCCESS":
      return { headline: "Access granted", subline: "Acoustic match confirmed. Vault unlocked." };
    case "DENIED":
      return { headline: "Access denied", subline: "Verification failed — see audit log for details." };
    default:
      return {
        headline: "Ready to capture",
        subline:
          "Read the challenge phrase aloud and press capture. Chaabi listens for a 1.2s window and matches your vocal fingerprint against the enrolled template.",
      };
  }
}

function formatTime() {
  return new Date().toLocaleTimeString("en-GB", { hour12: false });
}

function computePeakDeviation(dataArray: Uint8Array): number {
  let peak = 0;
  for (let i = 0; i < dataArray.length; i++) {
    const dev = Math.abs(dataArray[i] - 128) / 128;
    if (dev > peak) peak = dev;
  }
  return peak;
}

export default function AcousticConsole() {
  const [state, setState] = useState<ConsoleState>("IDLE");
  const [challenge, setChallenge] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [log, setLog] = useState<AuditEntry[]>([]);
  const [confidence, setConfidence] = useState<number | null>(null);
  const [readout, setReadout] = useState<Readout>({ snr: "—", peak: "—", f0: "—" });

  // Demo controls (accent is functionally real, forceVerdict overrides mock scenario)
  const [accent, setAccent] = useState("#2dd4bf");
  const [scanSpeed, setScanSpeed] = useState(1);
  const [forceVerdict, setForceVerdict] = useState<Verdict>("auto");

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const pcmChunksRef = useRef<Float32Array[]>([]);
  const animationFrameRef = useRef<number | null>(null);
  const readoutIntervalRef = useRef<number | null>(null);
  const peakRef = useRef(0);
  const scanSpeedRef = useRef(scanSpeed);

  useEffect(() => {
    scanSpeedRef.current = scanSpeed;
  }, [scanSpeed]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas) {
      canvas.width = canvas.clientWidth;
      canvas.height = 300;
      drawIdleGrid();
    }
    fetchChallenge();
    return () => abortRecording();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const appendLog = (tag: EventTag, text: string, meta?: string) => {
    setLog((prev) => [
      { id: crypto.randomUUID(), time: formatTime(), tag, text, meta },
      ...prev,
    ]);
  };

  async function fetchChallenge() {
    if (MOCK_MODE) {
      setChallenge("System override 809 validation allow");
      setSessionId("mock-session-" + Date.now());
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/api/challenge`);
      const data = await res.json();
      setChallenge(data.prompt);
      setSessionId(data.session_id);
    } catch {
      appendLog("DSP", "Failed to fetch challenge — backend unreachable");
    }
  }

  function drawGrid(ctx: CanvasRenderingContext2D, w: number, h: number) {
    ctx.strokeStyle = "rgba(255,255,255,0.05)";
    ctx.lineWidth = 1;
    for (let x = 0; x <= w; x += w / 6) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y <= h; y += h / 4) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }
  }

  function drawIdleGrid() {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    ctx.fillStyle = "#0a0b0d";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    drawGrid(ctx, canvas.width, canvas.height);
  }

  function drawWaveform() {
    const canvas = canvasRef.current;
    const analyser = analyserRef.current;
    if (!canvas || !analyser) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const bufferLength = analyser.fftSize;
    const dataArray = new Uint8Array(bufferLength);

    const render = () => {
      analyser.getByteTimeDomainData(dataArray);
      peakRef.current = computePeakDeviation(dataArray);

      const alpha = Math.min(0.9, Math.max(0.12, 0.35 * scanSpeedRef.current));
      ctx.fillStyle = `rgba(10, 11, 13, ${alpha})`;
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      drawGrid(ctx, canvas.width, canvas.height);

      ctx.lineWidth = 2;
      ctx.strokeStyle = accent;
      ctx.beginPath();

      const sliceWidth = canvas.width / bufferLength;
      let x = 0;
      for (let i = 0; i < bufferLength; i++) {
        const v = dataArray[i] / 128.0;
        const y = (v * canvas.height) / 2;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
        x += sliceWidth;
      }
      ctx.lineTo(canvas.width, canvas.height / 2);
      ctx.stroke();

      animationFrameRef.current = requestAnimationFrame(render);
    };
    render();
  }

  function resamplePCM(input: Float32Array, inRate: number, outRate: number): Float32Array {
    if (inRate === outRate) return input;
    const ratio = inRate / outRate;
    const newLength = Math.round(input.length / ratio);
    const result = new Float32Array(newLength);
    for (let i = 0; i < newLength; i++) {
      const srcIndex = i * ratio;
      const i0 = Math.floor(srcIndex);
      const i1 = Math.min(i0 + 1, input.length - 1);
      const frac = srcIndex - i0;
      result[i] = input[i0] * (1 - frac) + input[i1] * frac;
    }
    return result;
  }

  function encodeWAV(samples: Float32Array, sampleRate: number): Blob {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);
    const writeString = (offset: number, str: string) => {
      for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
    };
    writeString(0, "RIFF");
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(8, "WAVE");
    writeString(12, "fmt ");
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(36, "data");
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
      const s = Math.max(-1, Math.min(1, samples[i]));
      view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    }
    return new Blob([view], { type: "audio/wav" });
  }

  function stopEverything() {
    if (animationFrameRef.current) cancelAnimationFrame(animationFrameRef.current);
    processorRef.current?.disconnect();
    analyserRef.current?.disconnect();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.close();
    }
  }

  function abortRecording() {
    stopEverything();
    if (readoutIntervalRef.current) {
      clearInterval(readoutIntervalRef.current);
      readoutIntervalRef.current = null;
    }
  }

  async function startRecording() {
    if (!sessionId) {
      appendLog("DSP", "No active session — refresh the challenge first.");
      return;
    }

    setState("RECORDING");
    setLog([]);
    setConfidence(null);
    appendLog("CAPTURE", "Listening for acoustic key", "window 1.20s · 48kHz");
    pcmChunksRef.current = [];

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const AudioContextCtor =
        window.AudioContext || (window as any).webkitAudioContext;
      const audioCtx: AudioContext = new AudioContextCtor();
      audioCtxRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);

      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 2048;
      analyserRef.current = analyser;
      source.connect(analyser);

      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        const channelData = e.inputBuffer.getChannelData(0);
        pcmChunksRef.current.push(new Float32Array(channelData));
      };

      const muteGain = audioCtx.createGain();
      muteGain.gain.value = 0;
      source.connect(processor);
      processor.connect(muteGain);
      muteGain.connect(audioCtx.destination);

      drawWaveform();

      readoutIntervalRef.current = window.setInterval(() => {
        const dev = peakRef.current;
        const db = dev > 0 ? (20 * Math.log10(dev)).toFixed(1) : "-inf";
        setReadout((r) => ({ ...r, peak: db }));
      }, 200);

      setTimeout(() => finishRecording(audioCtx.sampleRate), RECORD_MS);
    } catch {
      appendLog("DSP", "Microphone access denied or unavailable.");
      setState("IDLE");
    }
  }

  async function finishRecording(sourceSampleRate: number) {
    abortRecording();
    appendLog("DSP", "Envelope aligned, 1.02s window", `frame ${TARGET_SAMPLE_RATE / 1000}k/16b`);
    setState("PROCESSING");

    const totalLength = pcmChunksRef.current.reduce((sum, c) => sum + c.length, 0);
    const merged = new Float32Array(totalLength);
    let offset = 0;
    for (const chunk of pcmChunksRef.current) {
      merged.set(chunk, offset);
      offset += chunk.length;
    }

    const resampled = resamplePCM(merged, sourceSampleRate, TARGET_SAMPLE_RATE);
    const wavBlob = encodeWAV(resampled, TARGET_SAMPLE_RATE);

    await sendForVerification(wavBlob);
  }

  function getMockResponse(): VerifyResponse {
    const scenario: MockScenario =
      forceVerdict === "grant" ? "success" : forceVerdict === "deny" ? "imposter" : MOCK_SCENARIO;

    switch (scenario) {
      case "replay":
        return { status: "DENIED", dsp: { is_replay_attack: true } };
      case "imposter":
        return {
          status: "DENIED",
          dsp: { is_replay_attack: false, F1: 612, F2: 1450, F3: 2610 },
          sarvam: { transcript: challenge ?? "", intent_valid: true },
          crypto: { vault_unlocked: false, error: "Formant drift exceeded 8% threshold" },
        };
      case "wrong_phrase":
        return {
          status: "DENIED",
          dsp: { is_replay_attack: false, F1: 730, F2: 1090, F3: 2440 },
          sarvam: { transcript: "an old, previously-used phrase", intent_valid: false },
        };
      case "success":
      default:
        return {
          status: "SUCCESS",
          dsp: { is_replay_attack: false, F1: 730, F2: 1090, F3: 2440 },
          sarvam: { transcript: challenge ?? "", intent_valid: true },
          crypto: {
            vault_unlocked: true,
            payload: "PROD_DB_LOCK_EXECUTED",
            confidence: 97.2,
          },
        };
    }
  }

  function handleVerifyResponse(data: VerifyResponse) {
    if (data.dsp) {
      if (data.dsp.is_replay_attack) {
        appendLog("DSP", "High-frequency spectral ratio exceeded threshold");
        appendLog("DENY", "Replay signature detected");
        setState("DENIED");
        return;
      }
      appendLog(
        "DSP",
        "Formants extracted",
        `F1 ${data.dsp.F1} · F2 ${data.dsp.F2} · F3 ${data.dsp.F3} Hz`
      );
    }

    if (data.sarvam) {
      appendLog("STT", `Transcript: "${data.sarvam.transcript ?? "—"}"`);
      if (!data.sarvam.intent_valid) {
        appendLog("INTENT", "Intent mismatch — halted");
        setState("DENIED");
        return;
      }
      appendLog("INTENT", "Intent verified — matches active challenge");
    }

    if (data.crypto) {
      if (data.crypto.vault_unlocked) {
        setConfidence(data.crypto.confidence ?? null);
        appendLog(
          "GRANT",
          "Acoustic match — above threshold",
          data.crypto.payload ? `payload ${data.crypto.payload}` : undefined
        );
      } else {
        appendLog("DENY", data.crypto.error ?? "Vault authentication failed");
      }
    }

    setState(data.status === "SUCCESS" ? "SUCCESS" : "DENIED");
  }

  async function sendForVerification(audioBlob: Blob) {
    if (!sessionId) return;

    if (MOCK_MODE) {
      await new Promise((r) => setTimeout(r, 700));
      handleVerifyResponse(getMockResponse());
      return;
    }

    const formData = new FormData();
    formData.append("session_id", sessionId);
    formData.append("audio", audioBlob, "challenge.wav");

    try {
      const res = await fetch(`${API_BASE}/api/verify`, { method: "POST", body: formData });
      const data: VerifyResponse = await res.json();
      handleVerifyResponse(data);
    } catch {
      appendLog("DSP", "Verification request failed — is the backend reachable?");
      setState("DENIED");
    }
  }

  function reset() {
    abortRecording();
    setState("IDLE");
    setLog([]);
    setConfidence(null);
    setReadout({ snr: "—", peak: "—", f0: "—" });
    drawIdleGrid();
    fetchChallenge();
  }

  const { headline, subline } = phaseCopy(state);

  return (
    <div
      className="min-h-screen p-8"
      style={{ ["--signal" as any]: accent, background: "var(--bg)" }}
    >
      <div className="mx-auto flex max-w-[1400px] flex-col gap-6">
        <ConsoleHeader sessionId={sessionId ?? "—"} device={DEVICE_LABEL} linkUp={true} />

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_380px]">
          <div className="flex flex-col gap-6">
            <ChallengePanel phrase={challenge ?? "loading…"} />
            <CapturePanel
              phase={PHASE_MAP[state]}
              headline={headline}
              subline={subline}
              readout={readout}
              confidence={confidence}
              canvasRef={canvasRef}
              onCapture={startRecording}
              onReset={reset}
              disabled={!sessionId}
            />
            <DemoControls
              accent={accent}
              onAccentChange={setAccent}
              scanSpeed={scanSpeed}
              onScanSpeedChange={setScanSpeed}
              forceVerdict={forceVerdict}
              onForceVerdictChange={setForceVerdict}
            />
          </div>

          <AuditLogPanel entries={log} />
        </div>
      </div>
    </div>
  );
}