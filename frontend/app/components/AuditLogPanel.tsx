import type { AuditEntry, EventTag } from "./types";

type Props = {
  entries: AuditEntry[];
  footer?: string;
};

const TAG_CLASS: Record<EventTag, string> = {
  ENROLL: "text-[var(--signal)] bg-[var(--signal)]/[.08]",
  GRANT: "text-[var(--ok)] bg-[var(--ok)]/[.11]",
  DENY: "text-[var(--danger)] bg-[var(--danger)]/[.10]",
  CAPTURE: "text-[var(--ink)]/80 bg-white/[.06]",
  DSP: "text-[var(--muted)] bg-white/[.05]",
  STT: "text-[var(--muted)] bg-white/[.05]",
  INTENT: "text-[var(--muted)] bg-white/[.05]",
};

export default function AuditLogPanel({
  entries,
  footer = "APPEND-ONLY · SIGNED EVENT STREAM",
}: Props) {
  return (
    <aside className="sticky top-6 flex min-w-0 flex-col rounded-[14px] border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex items-center justify-between border-b border-[var(--border)] px-[18px] py-4">
        <div className="font-mono text-[11px] tracking-[0.18em] text-[var(--muted)]">
          AUDIT LOG
        </div>
        <div className="whitespace-nowrap font-mono text-[10.5px] text-[var(--muted)]">
          {entries.length} events
        </div>
      </div>

      <div className="flex max-h-[620px] flex-col overflow-y-auto">
        {entries.map((e) => (
          <div
            key={e.id}
            className="grid grid-cols-[74px_minmax(0,1fr)] gap-3 border-b border-[var(--border)]/60 px-[18px] py-3.5"
          >
            <div className="pt-0.5 font-mono text-[10.5px] text-[var(--muted)]">{e.time}</div>
            <div className="flex min-w-0 flex-col gap-1.5">
              <div className="flex items-center gap-2">
                <span className={`rounded-[5px] px-1.5 py-0.5 font-mono text-[9.5px] tracking-[0.1em] ${TAG_CLASS[e.tag]}`}>
                  {e.tag}
                </span>
                <span className="text-[13px] text-[var(--ink)]/85">{e.text}</span>
              </div>
              {e.meta ? (
                <div className="truncate font-mono text-[10px] text-[var(--muted)]/80">{e.meta}</div>
              ) : null}
            </div>
          </div>
        ))}
      </div>

      <div className="border-t border-[var(--border)] px-[18px] py-3.5 font-mono text-[10px] tracking-[0.1em] text-[var(--muted)]">
        {footer}
      </div>
    </aside>
  );
}
