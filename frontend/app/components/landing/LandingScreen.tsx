"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import CipherField from "./CipherField";
import KeyMotif from "./KeyMotif";
import { useDecrypt } from "./useDecrypt";

const REACT_MS = 360;
const EXIT_MS = 560;

type Props = {
  onSequenceComplete: () => void;
};

export default function LandingScreen({ onSequenceComplete }: Props) {
  const [stage, setStage] = useState<"idle" | "react" | "exit">("idle");
  const reduceMotion = useReducedMotion();
  const timerRef = useRef<number | null>(null);
  const text = useDecrypt(
    {
      wordmark: "CHAABI",
      subtitle: "Cryptographic Hybrid Audio Authentication & Biometric Identity",
    },
    { wordmark: { hold: 4 }, subtitle: { delay: 5, hold: 0.32 } },
  );

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  const enter = useCallback(() => {
    if (stage !== "idle") return;
    if (reduceMotion) {
      setStage("exit");
      return;
    }
    setStage("react");
    timerRef.current = window.setTimeout(() => setStage("exit"), REACT_MS);
  }, [reduceMotion, stage]);

  return (
    <div className="relative min-h-screen cursor-pointer overflow-hidden bg-[var(--bg)]">
      <CipherField />
      <button
        type="button"
        aria-label="Enter the CHAABI authentication dashboard"
        onClick={enter}
        disabled={stage !== "idle"}
        className="landing-entry-trigger absolute inset-0 z-20 cursor-pointer bg-transparent disabled:cursor-wait"
      />

      <motion.div
        initial={{ opacity: 1, scale: 1 }}
        animate={stage === "exit" ? { opacity: 0, scale: 1.06 } : { opacity: 1, scale: 1 }}
        transition={{
          duration: reduceMotion ? 0.12 : EXIT_MS / 1000,
          ease: [0.22, 0.61, 0.36, 1],
        }}
        onAnimationComplete={() => {
          if (stage === "exit") onSequenceComplete();
        }}
        style={{ willChange: "opacity, transform" }}
        className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-7 p-6 sm:p-10"
      >
        <h1 className="whitespace-nowrap text-[clamp(48px,9vw,132px)] font-medium leading-none tracking-[0.18em] text-[var(--ink)]">
          {text.wordmark}
        </h1>
        <p className="max-w-[62ch] text-center text-[clamp(14px,1.5vw,21px)] leading-relaxed text-[var(--ink)]">
          {text.subtitle}
        </p>
        <p className="text-sm font-light tracking-wide text-[var(--muted)]">Your voice is the key</p>
        <KeyMotif stage={stage} reactMs={REACT_MS} />
        <p className="text-center text-xs tracking-[0.34em] text-[var(--muted)]">
          CLICK ANYWHERE TO ENTER
        </p>
      </motion.div>
    </div>
  );
}
