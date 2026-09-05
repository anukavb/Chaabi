export type Phase = "idle" | "listening" | "analyzing" | "verified" | "denied";

export type EventTag = "CAPTURE" | "DSP" | "STT" | "INTENT" | "GRANT" | "DENY";

export type AuditEntry = {
  id: string;
  time: string;   // preformatted, e.g. "11:03:52"
  tag: EventTag;
  text: string;
  meta?: string;  // secondary mono line, e.g. "tokens 5/5"
};

export type Readout = {
  snr: string;
  peak: string;
  f0: string;
};