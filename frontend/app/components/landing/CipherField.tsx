"use client";

import { useEffect, useRef } from "react";

const SYMBOLS = ["⊕", "⊗", "∑", "∫", "≡", "λ", "π", "σ", "∧", "∨", "¬", "√", "⊥", "∈", "⌈", "⌉", "∞", "μ"];
const TOKENS = ["0xA3", "H(m)", "g^k", "mod p", "2^n", "sha256", "k ∈ Z", "σ(x)", "f0", "48k", "⊕ nonce", "HMAC"];

type Cell = { x: number; y: number; token: boolean; glyph: string; lit: boolean; level: number };

type Props = {
  step?: number;
  radius?: number;
  className?: string;
};

function toRgbTriplet(input: string, fallback = "94,234,212") {
  const probe = document.createElement("span");
  probe.style.color = input;
  probe.style.display = "none";
  document.body.appendChild(probe);
  const resolved = getComputedStyle(probe).color;
  probe.remove();
  const match = resolved.match(/-?[\d.]+/g);
  return match && match.length >= 3 ? `${match[0]},${match[1]},${match[2]}` : fallback;
}

export default function CipherField({ step = 56, radius = 190, className = "" }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;

    const signal = getComputedStyle(canvas).getPropertyValue("--signal").trim() || "rgb(94 234 212)";
    const rgb = toRgbTriplet(signal);
    const pick = <T,>(items: T[]) => items[Math.floor(Math.random() * items.length)];
    let cells: Cell[] = [];
    let lastWidth = 0;
    let lastHeight = 0;

    const build = (width: number, height: number) => {
      cells = [];
      for (let y = step; y < height; y += step) {
        for (let x = step; x < width; x += step) {
          const token = (x * 7 + y * 13) % 13 === 0;
          cells.push({
            x: x + (((x * 31 + y * 17) % 9) - 4),
            y: y + (((x * 13 + y * 29) % 9) - 4),
            token,
            glyph: token ? pick(TOKENS) : pick(SYMBOLS),
            lit: false,
            level: 0,
          });
        }
      }
      lastWidth = width;
      lastHeight = height;
    };

    let mouseX: number | null = null;
    let mouseY: number | null = null;
    let cursorX = 0;
    let cursorY = 0;
    const onPointerMove = (event: PointerEvent) => {
      mouseX = event.clientX;
      mouseY = event.clientY;
    };
    window.addEventListener("pointermove", onPointerMove, { passive: true });

    let animationFrame = 0;
    const draw = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (width && height) {
        if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
          canvas.width = width * dpr;
          canvas.height = height * dpr;
        }
        if (!cells.length || lastWidth !== width || lastHeight !== height) build(width, height);

        context.setTransform(dpr, 0, 0, dpr, 0, 0);
        context.clearRect(0, 0, width, height);
        if (mouseX !== null && mouseY !== null) {
          const bounds = canvas.getBoundingClientRect();
          const targetX = mouseX - bounds.left;
          const targetY = mouseY - bounds.top;
          if (!cursorX && !cursorY) {
            cursorX = targetX;
            cursorY = targetY;
          }
          cursorX += (targetX - cursorX) * 0.12;
          cursorY += (targetY - cursorY) * 0.12;
          context.textAlign = "center";
          context.textBaseline = "middle";

          for (const cell of cells) {
            const distance = Math.hypot(cell.x - cursorX, cell.y - cursorY);
            const target = distance > radius ? 0 : Math.pow(1 - distance / radius, 1.5);
            cell.level += (target - cell.level) * (target > cell.level ? 0.2 : 0.03);
            const alpha = cell.level * (cell.token ? 0.4 : 0.55);
            if (alpha < 0.02) {
              cell.lit = false;
              continue;
            }
            if (!cell.lit) {
              cell.lit = true;
              cell.glyph = cell.token ? pick(TOKENS) : pick(SYMBOLS);
            }
            context.font = `${cell.token ? "400 10px" : "500 13px"} var(--font-geist-mono), ui-monospace, monospace`;
            context.fillStyle = `rgba(${rgb},${alpha.toFixed(3)})`;
            context.fillText(cell.glyph, cell.x, cell.y);
          }
        }
      }
      animationFrame = requestAnimationFrame(draw);
    };

    animationFrame = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(animationFrame);
      window.removeEventListener("pointermove", onPointerMove);
    };
  }, [radius, step]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className={`pointer-events-none absolute inset-0 size-full ${className}`}
    />
  );
}
