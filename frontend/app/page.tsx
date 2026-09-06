"use client";

import { useState } from "react";
import AcousticConsole from "./components/AcousticConsole";
import LandingScreen from "./components/landing/LandingScreen";

export default function Home() {
  const [entered, setEntered] = useState(false);

  return (
    <div className="relative min-h-screen bg-[var(--bg)]">
      <div aria-hidden={!entered} inert={!entered ? true : undefined}>
        <AcousticConsole />
      </div>

      {!entered && (
        <div className="fixed inset-0 z-50">
          <LandingScreen onSequenceComplete={() => setEntered(true)} />
        </div>
      )}
    </div>
  );
}
