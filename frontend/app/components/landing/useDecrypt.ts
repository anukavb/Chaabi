"use client";

import { useEffect, useMemo, useState } from "react";

const CIPHER = "⊕⊗∑∏∫≡λπσφ∧∨¬√∞⊂∈⊥⌈⌉0123456789ABCDEF";

export type DecryptLine = {
  delay?: number;
  hold?: number;
};

export function useDecrypt(
  lines: Record<string, string>,
  options: Record<string, DecryptLine> = {},
) {
  const serializedLines = JSON.stringify(lines);
  const serializedOptions = JSON.stringify(options);
  const currentLines = useMemo(
    () => JSON.parse(serializedLines) as Record<string, string>,
    [serializedLines],
  );
  const currentOptions = useMemo(
    () => JSON.parse(serializedOptions) as Record<string, DecryptLine>,
    [serializedOptions],
  );
  const [output, setOutput] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.keys(currentLines).map((key) => [key, ""])),
  );

  useEffect(() => {
    const keys = Object.keys(currentLines);
    let frame = 0;
    const randomCharacter = () => CIPHER[Math.floor(Math.random() * CIPHER.length)];

    const interval = window.setInterval(() => {
      frame += 1;
      const next: Record<string, string> = {};
      let complete = true;

      for (const key of keys) {
        const text = currentLines[key];
        const { delay = 0, hold = 2 } = currentOptions[key] ?? {};
        const locked = Math.floor((frame - delay) / hold);

        if (locked >= text.length) {
          next[key] = text;
          continue;
        }

        complete = false;
        next[key] =
          locked < 0
            ? text.replace(/\S/g, randomCharacter)
            : text
                .split("")
                .map((character, index) =>
                  index < locked || character === " " ? character : randomCharacter(),
                )
                .join("");
      }

      setOutput(next);
      if (complete) window.clearInterval(interval);
    }, 45);

    return () => window.clearInterval(interval);
  }, [currentLines, currentOptions]);

  return output;
}
