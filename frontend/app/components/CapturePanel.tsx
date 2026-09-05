import type { RefObject } from "react";
import type { Phase, Readout } from "./types";

type Props = {
  phase: Phase;
  headline: string;
  subline: string;
  readout: Readout;
  confidence: number | null;      // 0–100, null when idle
  canvasRef: RefObject<HTMLCanvasElement | null>;
  onCapture: () => void;
  onReset: () => void;
  captureLabel?: string;          // e.g. "CAPTURE" | "ABORT" | "AGAIN"
  disabled?: boolean;
};

const PHASE_LABEL: Record<Phase, string> = {
  idle: "STANDBY",
  listening: "LISTENING",
  analyzing: "ANALYZING",
  verified: "VERIFIED",
  denied: "DENIED",
};

function phaseTone(phase: Phase) {
  if (phase === "denied") return "text-[var(--danger)] border-[var(--danger)]/40 bg-[var(--danger)]/[.09]";
  if (phase === "idle") return "text-[var(--muted)] border-[var(--border)] bg-white/[.03]";
  return "text-[var(--signal)] border-[var(--signal)]/35 bg-[var(--signal)]/[.08]";
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-end gap-[3px]">
      <div className="font-mono text-[10px] tracking-[0.12em] text-[var(--muted)]">{label}</div>
      <div className="font-mono text-sm text-[var(--ink)]">{value}</div>
    </div>
  );
}

export default function CapturePanel({
  phase,
  headline,
  subline,
  readout,
  confidence,
  canvasRef,
  onCapture,
  onReset,
  captureLabel = "CAPTURE",
  disabled = false,
}: Props) {
  const busy = phase === "listening" || phase === "analyzing";
  const barColor = phase === "denied" ? "bg-[var(--danger)]" : "bg-[var(--signal)]";

  return (
    <div className="flex flex-col gap-[18px]">
      {/* control row */}
      <section className="flex flex-wrap items-center gap-[26px] rounded-[14px] border border-[var(--border)] bg-[var(--surface)] px-6 py-5">
        <button
          type="button"
          onClick={busy ? onReset : onCapture}
          disabled={disabled}
          className={`flex size-[86px] shrink-0 items-center justify-center rounded-full border font-mono text-[11px] tracking-[0.12em] transition-transform hover:scale-[1.04] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 ${
            busy
              ? "border-[var(--signal)]/35 bg-[var(--signal)]/[.12] text-[var(--signal)]"
              : phase === "denied"
                ? "border-[var(--danger)]/40 bg-[var(--danger)]/[.12] text-[var(--danger)]"
                : "border-transparent bg-[var(--signal)] text-[var(--bg)] shadow-[0_0_40px_var(--signal)]/25"
          }`}
        >
          {busy ? "ABORT" : captureLabel}
        </button>

        <div className="flex min-w-[240px] flex-1 flex-col gap-2">
          <div className="text-[17px] font-medium text-[var(--ink)]">{headline}</div>
          <p className="max-w-[60ch] text-[13.5px] leading-relaxed text-[var(--muted)] text-pretty">
            {subline}
          </p>
        </div>

        <div className="flex min-w-[190px] flex-col gap-2.5">
          <div className="flex justify-between font-mono text-[10.5px] tracking-[0.12em] text-[var(--muted)]">
            <span>MATCH CONFIDENCE</span>
            <span className="text-[var(--ink)]">
              {confidence === null ? "—" : (confidence / 100).toFixed(3)}
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-md bg-white/[.06]">
            <div
              className={`h-full rounded-md transition-[width] duration-500 ${barColor}`}
              style={{ width: `${confidence ?? 0}%` }}
            />
          </div>
          <button
            type="button"
            onClick={onReset}
            className="rounded-lg border border-[var(--border)] px-3 py-[9px] font-mono text-[10.5px] tracking-[0.1em] text-[var(--muted)] transition-colors hover:bg-white/[.05] hover:text-[var(--ink)]"
          >
            RESET
          </button>
        </div>
      </section>

      {/* scope */}
      <section className="overflow-hidden rounded-[14px] border border-[var(--border)] bg-[var(--surface)]">
        <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[var(--border)] px-[22px] py-4">
          <div className="flex items-center gap-3">
            <div className="font-mono text-[11px] tracking-[0.18em] text-[var(--muted)]">
              ACOUSTIC CAPTURE
            </div>
            <div className={`rounded-full border px-2.5 py-1 font-mono text-[10.5px] tracking-[0.1em] ${phaseTone(phase)}`}>
              {PHASE_LABEL[phase]}
            </div>
          </div>
          <div className="flex items-center gap-[22px]">
            <Stat label="SNR" value={`${readout.snr} dB`} />
            <Stat label="PEAK" value={`${readout.peak} dBFS`} />
            <Stat label="F0" value={`${readout.f0} Hz`} />
          </div>
        </div>

        <div className="px-2.5 pb-1 pt-2">
          <canvas ref={canvasRef} className="block h-[300px] w-full" />
        </div>

        <div className="flex justify-between px-[22px] pb-3.5 font-mono text-[10px] tracking-[0.1em] text-[var(--muted)]">
          <span>0 ms</span><span>200</span><span>400</span>
          <span>600</span><span>800</span><span>1000 ms</span>
        </div>
      </section>
    </div>
  );
}