"use client";

import { useEffect, useRef } from "react";

type Props = {
  stage: "idle" | "react" | "exit";
  reactMs?: number;
  width?: number;
  height?: number;
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

export default function KeyMotif({ stage, reactMs = 360, width = 380, height = 140 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const clickAt = useRef(0);

  useEffect(() => {
    if (stage === "react" && !clickAt.current) clickAt.current = performance.now();
    if (stage === "idle") clickAt.current = 0;
  }, [stage]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const context = canvas?.getContext("2d");
    if (!canvas || !context) return;

    const signal = getComputedStyle(canvas).getPropertyValue("--signal").trim() || "rgb(94 234 212)";
    const rgb = toRgbTriplet(signal);
    const teal = `rgba(${rgb},`;
    const startedAt = performance.now();
    let animationFrame = 0;

    const draw = (now: number) => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const canvasWidth = canvas.clientWidth;
      const canvasHeight = canvas.clientHeight;
      if (canvasWidth && canvasHeight) {
        if (canvas.width !== canvasWidth * dpr || canvas.height !== canvasHeight * dpr) {
          canvas.width = canvasWidth * dpr;
          canvas.height = canvasHeight * dpr;
        }
        context.setTransform(dpr, 0, 0, dpr, 0, 0);
        context.clearRect(0, 0, canvasWidth, canvasHeight);

        const time = (now - startedAt) / 1000;
        const progress = clickAt.current ? Math.min((now - clickAt.current) / reactMs, 1) : 0;
        const eased = progress * progress * (3 - 2 * progress);
        const middle = canvasHeight / 2;
        const ring = 23;
        const ringX = 88;
        const hinge = ringX + ring;
        const tip = canvasWidth - 84;
        const amplitude = 3.2 + eased * 17;

        if (clickAt.current) {
          const radius = 40 + eased * 240;
          const bloom = context.createRadialGradient(canvasWidth / 2, middle, 0, canvasWidth / 2, middle, radius);
          bloom.addColorStop(0, `${teal}${(0.3 * (1 - eased)).toFixed(3)})`);
          bloom.addColorStop(0.5, `${teal}${(0.1 * (1 - eased)).toFixed(3)})`);
          bloom.addColorStop(1, `rgba(${rgb},0)`);
          context.fillStyle = bloom;
          context.fillRect(0, 0, canvasWidth, canvasHeight);
        }

        context.lineCap = "round";
        context.lineJoin = "round";
        context.shadowColor = signal;
        context.shadowBlur = 10 + eased * 12;
        context.strokeStyle = `${teal}${(0.62 + eased * 0.3).toFixed(3)})`;
        context.lineWidth = 1.4;

        const gap = 0.1 + eased * 0.95;
        context.save();
        context.translate(ringX, middle);
        context.rotate(-eased * 0.34);
        context.beginPath();
        context.arc(0, 0, ring, gap / 2, Math.PI * 2 - gap / 2);
        context.stroke();
        context.restore();

        const bend = hinge + (tip - hinge) * 0.6;
        context.beginPath();
        context.moveTo(hinge, middle);
        for (let x = hinge; x <= bend; x += 2) {
          const position = (x - hinge) / (bend - hinge);
          const taper = Math.pow(Math.sin(Math.PI * Math.min(position * 1.25, 1)), 0.7);
          const y =
            middle +
            taper *
              (Math.sin(position * 26 + time * 4.4) * amplitude * 0.5 +
                Math.sin(position * 57 + time * 8) * amplitude * 0.26 +
                Math.sin(position * 11 - time * 2.3) * amplitude * 0.3);
          context.lineTo(x, y);
        }
        context.lineTo(tip, middle);
        context.stroke();

        const teeth: [number, number, number][] = [
          [0.1, 0.3, 13],
          [0.46, 0.62, 9],
          [0.74, 0.86, 16],
        ];
        const span = tip - bend;
        context.beginPath();
        for (const [start, end, depth] of teeth) {
          context.moveTo(bend + span * start, middle);
          context.lineTo(bend + span * start, middle + depth);
          context.lineTo(bend + span * end, middle + depth);
          context.lineTo(bend + span * end, middle);
        }
        context.stroke();
        context.shadowBlur = 0;
      }
      animationFrame = requestAnimationFrame(draw);
    };

    animationFrame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animationFrame);
  }, [reactMs]);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{ width, height }}
      className="block max-w-full"
    />
  );
}
