type Verdict = "auto" | "grant" | "deny";

type Props = {
  accent: string;
  accentOptions?: string[];
  onAccentChange: (value: string) => void;
  scanSpeed: number;
  onScanSpeedChange: (value: number) => void;
  forceVerdict: Verdict;
  onForceVerdictChange: (value: Verdict) => void;
};

const label = "font-mono text-[10px] tracking-[0.14em] text-[var(--muted)]";

export default function DemoControls({
  accent,
  accentOptions = ["#2dd4bf", "#7dd3fc", "#a3e635", "#f0abfc"],
  onAccentChange,
  scanSpeed,
  onScanSpeedChange,
  forceVerdict,
  onForceVerdictChange,
}: Props) {
  return (
    <div className="flex flex-wrap items-center gap-6 rounded-[14px] border border-[var(--border)] bg-[var(--surface)] px-5 py-3.5">
      <div className="flex items-center gap-2.5">
        <span className={label}>ACCENT</span>
        <div className="flex gap-1.5">
          {accentOptions.map((c) => (
            <button
              key={c}
              type="button"
              aria-label={`Accent ${c}`}
              aria-pressed={accent === c}
              onClick={() => onAccentChange(c)}
              style={{ background: c }}
              className={`size-4 rounded-full transition-transform hover:scale-110 ${
                accent === c ? "ring-2 ring-[var(--ink)]/70 ring-offset-2 ring-offset-[var(--surface)]" : ""
              }`}
            />
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2.5">
        <span className={label}>SCAN SPEED</span>
        <input
          type="range"
          min={0.5}
          max={2.5}
          step={0.1}
          value={scanSpeed}
          onChange={(e) => onScanSpeedChange(Number(e.target.value))}
          className="h-1 w-28 accent-[var(--signal)]"
        />
        <span className="font-mono text-[10.5px] text-[var(--ink)]">{scanSpeed.toFixed(1)}×</span>
      </div>

      <div className="flex items-center gap-2">
        <span className={label}>VERDICT</span>
        <div className="flex overflow-hidden rounded-lg border border-[var(--border)]">
          {(["auto", "grant", "deny"] as Verdict[]).map((v) => (
            <button
              key={v}
              type="button"
              aria-pressed={forceVerdict === v}
              onClick={() => onForceVerdictChange(v)}
              className={`px-2.5 py-1.5 font-mono text-[10px] uppercase tracking-[0.1em] transition-colors ${
                forceVerdict === v
                  ? "bg-white/[.08] text-[var(--ink)]"
                  : "text-[var(--muted)] hover:bg-white/[.04]"
              }`}
            >
              {v}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}