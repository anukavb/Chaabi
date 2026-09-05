export type Phase = "idle" | "listening" | "analyzing" | "verified" | "denied";

export type EventTag = "ENROLL" | "CAPTURE" | "DSP" | "STT" | "INTENT" | "GRANT" | "DENY";

export type AuditEntry = {
  id: string;
  time: string;   // preformatted, e.g. "11:03:52"
  tag: EventTag;
  text: string;
  meta?: string;  // secondary mono line, e.g. "tokens 5/5"
};

export type Readout = {
  peak: string;
  sampleRate: string;
  frames: string;
};

export type CheckStatus = "pending" | "running" | "passed" | "failed" | "skipped";

export type VerificationCheck = {
  id: string;
  label: string;
  status: CheckStatus;
  detail?: string;
};

export type DspResult = {
  formant_frames: Array<{
    frame_id: number;
    f1_hz: number;
    f2_hz: number;
    f3_hz: number;
    confidence: number;
  }>;
  formant_summary: {
    f1_hz: number | null;
    f2_hz: number | null;
    f3_hz: number | null;
  };
  liveness_score: number | null;
  is_replay_attack: boolean;
  liveness_available: boolean;
  audio_quality: {
    sample_rate: number;
    duration_ms: number;
    speech_detected: boolean;
    clipping_detected: boolean;
    peak: number;
    rms: number;
  };
  features: { high_frequency_energy_ratio: number | null };
  reason_codes: string[];
};

export type AuthResponse = {
  authenticated: boolean;
  message: string;
  reason: string;
  transcript: string | null;
  challenge_matched: boolean;
  dsp: DspResult | null;
  speaker: {
    matched: boolean;
    similarity: number | null;
    threshold: number | null;
    template_similarities: number[];
    error: string | null;
  } | null;
  crypto: {
    vault_unlocked: boolean;
    matched_points: number;
    required_points: number;
    error: string | null;
    confidence: number | null;
  } | null;
};
