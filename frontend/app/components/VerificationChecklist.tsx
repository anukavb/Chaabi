import type { CheckStatus, VerificationCheck } from "./types";

type Props = {
  title: string;
  checks: VerificationCheck[];
};

const STATUS_COPY: Record<CheckStatus, string> = {
  pending: "WAITING",
  running: "CHECKING",
  passed: "PASSED",
  failed: "FAILED",
  skipped: "SKIPPED",
};

function statusClasses(status: CheckStatus) {
  if (status === "passed") {
    return "border-[var(--signal)] bg-[var(--signal)] text-[var(--bg)]";
  }
  if (status === "failed") {
    return "border-[var(--danger)] bg-[var(--danger)]/[.12] text-[var(--danger)]";
  }
  if (status === "running") {
    return "border-[var(--signal)] text-[var(--signal)] animate-pulse";
  }
  return "border-[var(--border)] text-[var(--muted)]";
}

function statusMark(status: CheckStatus) {
  if (status === "passed") return "✓";
  if (status === "failed") return "×";
  if (status === "running") return "·";
  if (status === "skipped") return "–";
  return "";
}

export default function VerificationChecklist({ title, checks }: Props) {
  const passed = checks.filter((check) => check.status === "passed").length;

  return (
    <section className="overflow-hidden rounded-[14px] border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-4">
        <div className="font-mono text-[11px] tracking-[0.18em] text-[var(--muted)]">
          {title}
        </div>
        <div className="font-mono text-[10px] tracking-[0.12em] text-[var(--muted)]">
          {passed}/{checks.length} PASSED
        </div>
      </div>

      <div className="divide-y divide-[var(--border)]">
        {checks.map((check) => (
          <div key={check.id} className="flex items-start gap-3 px-5 py-3.5">
            <div
              aria-hidden="true"
              className={`mt-0.5 flex size-5 shrink-0 items-center justify-center rounded border font-mono text-xs ${statusClasses(check.status)}`}
            >
              {statusMark(check.status)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[13px] text-[var(--ink)]">{check.label}</span>
                <span className="font-mono text-[9px] tracking-[0.1em] text-[var(--muted)]">
                  {STATUS_COPY[check.status]}
                </span>
              </div>
              {check.detail ? (
                <div className="mt-1 font-mono text-[10px] leading-relaxed text-[var(--muted)]">
                  {check.detail}
                </div>
              ) : null}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
