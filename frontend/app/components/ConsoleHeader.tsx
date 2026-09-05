type Props = {
  sessionId: string;
  device: string;          // e.g. "MIC-01 · 48kHz"
  linkLabel?: string;      // e.g. "DSP LINK OK"
  linkUp?: boolean;
};

const chip =
  "flex items-center gap-2 rounded-lg border border-[var(--border)] bg-white/[.02] px-3 py-[7px] font-mono text-[11px] text-[var(--muted)]";

export default function ConsoleHeader({
  sessionId,
  device,
  linkLabel = "DSP LINK OK",
  linkUp = true,
}: Props) {
  return (
    <header className="flex flex-wrap items-center justify-between gap-6 border-b border-[var(--border)] pb-4">
      <div className="flex items-center gap-3.5">
        <div className="flex size-[26px] items-center justify-center rounded-[7px] bg-[var(--signal)] font-mono text-[13px] font-medium text-[var(--bg)] shadow-[0_0_22px_var(--signal)]/30">
          C
        </div>
        <div className="flex flex-col gap-[3px]">
          <div className="text-[15px] font-semibold tracking-[0.22em] text-[var(--ink)]">
            CHAABI
          </div>
          <div className="font-mono text-[10.5px] tracking-[0.16em] text-[var(--muted)]">
            ACOUSTIC AUTHENTICATION CONSOLE
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        <div className={chip}>
          SESSION <span className="text-[var(--ink)]">{sessionId}</span>
        </div>
        <div className={chip}>
          DEVICE <span className="text-[var(--ink)]">{device}</span>
        </div>
        <div
          className={
            linkUp
              ? "flex items-center gap-2.5 rounded-lg border border-[var(--signal)]/25 bg-[var(--signal)]/[.06] px-[13px] py-[7px] font-mono text-[11px] text-[var(--signal)]"
              : "flex items-center gap-2.5 rounded-lg border border-[var(--danger)]/30 bg-[var(--danger)]/[.06] px-[13px] py-[7px] font-mono text-[11px] text-[var(--danger)]"
          }
        >
          <span
            className={`size-1.5 rounded-full ${
              linkUp ? "bg-[var(--signal)] animate-pulse" : "bg-[var(--danger)]"
            }`}
          />
          {linkUp ? linkLabel : "DSP LINK DOWN"}
        </div>
      </div>
    </header>
  );
}