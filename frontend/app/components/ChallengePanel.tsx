type Props = {
  phrase: string;
  label?: string;
};

export default function ChallengePanel({
  phrase,
  label = "READ THIS PHRASE ALOUD",
}: Props) {
  return (
    <section className="flex flex-col gap-3.5 rounded-[14px] border border-[var(--border)] bg-[var(--surface)] px-6 py-[22px]">
      <div className="font-mono text-[11px] tracking-[0.18em] text-[var(--muted)]">
        {label}
      </div>
      <div className="font-mono text-[30px] font-medium leading-[1.28] tracking-[0.02em] text-[var(--ink)] text-pretty">
        {phrase}
      </div>
    </section>
  );
}