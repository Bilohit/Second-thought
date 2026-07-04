// gui/src/components/PillMenu/FluidVisualizer.tsx
/**
 * Siri-style fluid audio visualizer. Two variants:
 *  - "line": layered drifting harmonics under a center-weighted envelope
 *    (capture panel / capsule bar).
 *  - "ring": harmonically wobbling circle wrapped around the minimal pill.
 * Level = gated smoothed mic RMS (waveform.ts math). Theme-colored: layers
 * blend --recording and --accent so it matches every theme automatically.
 * DPI-aware; buffers reused per mount — zero alloc per frame.
 */
import { useEffect, useRef } from "react";
import { rms, updateNoiseFloor } from "../../lib/waveform";
import { smoothLevel, fluidCurve, fluidRing, LAYERS, perceptualLevel, bandLevels } from "../../lib/fluidviz";

interface Props {
  readWaveform: (out: Float32Array) => void;
  readSpectrum?: (out: Uint8Array) => void;
  sampleRate?: number;
  width?: number;
  height: number;
  active: boolean;
  variant?: "line" | "ring";
}

const POINTS = 64;
const RING_POINTS = 72;
const LAYER_ALPHA = [0.85, 0.5, 0.3];
const SPECTRUM_SIZE = 1024;
const FFT_SIZE = 2048;

export default function FluidVisualizer({ readWaveform, readSpectrum, sampleRate, width, height, active, variant = "line" }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1; // re-read per mount: multi-monitor DPI
    let w = width ?? 0;
    let resizeObserver: ResizeObserver | undefined;
    if (width === undefined) {
      const parent = canvas.parentElement;
      w = parent?.clientWidth ?? 0;
      canvas.width = w * dpr;
      canvas.style.width = w + "px";
    } else {
      canvas.width = w * dpr;
    }
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    if (width === undefined && canvas.parentElement) {
      resizeObserver = new ResizeObserver((entries) => {
        const entry = entries[0];
        if (!entry) return;
        w = entry.contentRect.width;
        canvas.width = w * dpr;
        canvas.style.width = w + "px";
        ctx.scale(dpr, dpr);
      });
      resizeObserver.observe(canvas.parentElement);
    }
    const rootStyle = getComputedStyle(document.documentElement);
    const colRecording = rootStyle.getPropertyValue("--recording").trim() || "#c25b52";
    const colAccent = rootStyle.getPropertyValue("--accent").trim() || "#737373";
    const layerColors = [colRecording, colAccent, colRecording];

    const buf = new Float32Array(2048);
    const spec = new Uint8Array(SPECTRUM_SIZE);
    const pts = new Array<number>(Math.max(POINTS, RING_POINTS));
    let floor = 0.005; // starting noise-floor guess; adapts within ~1s
    let level = 0;
    const layerLevels = [0, 0, 0];
    let raf = 0;
    const t0 = performance.now();

    const draw = () => {
      const t = (performance.now() - t0) / 1000;
      ctx.clearRect(0, 0, w, height);
      let target = 0;
      if (active) {
        readWaveform(buf);
        const frameRms = rms(buf);
        floor = updateNoiseFloor(floor, frameRms);
        target = perceptualLevel(frameRms, floor);
      }
      if (active && readSpectrum) {
        readSpectrum(spec);
        const bands = bandLevels(spec, sampleRate ?? 48000, FFT_SIZE);
        for (let l = 0; l < 3; l++) {
          layerLevels[l] = smoothLevel(layerLevels[l], target * (0.4 + 0.6 * bands[l]), 0.5, 0.12);
        }
      } else {
        level = active ? smoothLevel(level, target) : 0;
      }
      // 0.06 idle breath: alive-but-listening, never flat while active
      const usingBands = active && !!readSpectrum;
      const drawLevel = active ? Math.max(usingBands ? Math.max(...layerLevels) : level, 0.06) : 0;

      if (variant === "ring") {
        if (drawLevel > 0) {
          const cx = w / 2;
          const cy = height / 2;
          const R = Math.min(w, height) / 2 - 3;
          // Dual orbit (user-locked Q2): recording ring plus a smaller accent
          // ring drifting the OPPOSITE direction at a slightly lower level.
          const orbits = [
            { r: R,     tt: t,          lvl: drawLevel,       col: colRecording, alpha: 0.9, lw: 1.4 },
            { r: R - 2, tt: -t * 1.3 + 3, lvl: drawLevel * 0.8, col: colAccent,   alpha: 0.6, lw: 1.2 },
          ];
          for (const o of orbits) {
            fluidRing(RING_POINTS, o.tt, o.lvl, pts);
            ctx.beginPath();
            for (let i = 0; i <= RING_POINTS; i++) {
              const th = ((i % RING_POINTS) / RING_POINTS) * 2 * Math.PI;
              const r = o.r * pts[i % RING_POINTS];
              const x = cx + Math.cos(th) * r;
              const y = cy + Math.sin(th) * r;
              i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
            }
            ctx.closePath();
            ctx.lineWidth = o.lw;
            ctx.globalAlpha = o.alpha;
            ctx.strokeStyle = o.col;
            ctx.stroke();
          }
        }
      } else {
        const mid = height / 2;
        if (drawLevel > 0) {
          for (let l = 0; l < LAYERS.length; l++) {
            const layerLevel = usingBands ? Math.max(layerLevels[l], 0.06) : drawLevel;
            fluidCurve(POINTS, t, layerLevel, LAYERS[l], pts);
            ctx.beginPath();
            for (let i = 0; i < POINTS; i++) {
              const x = (i / (POINTS - 1)) * w;
              const y = mid - pts[i] * (mid - 1.5);
              i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
            }
            ctx.lineWidth = l === 0 ? 1.8 : 1.2;
            ctx.lineJoin = "round";
            ctx.globalAlpha = LAYER_ALPHA[l];
            ctx.strokeStyle = layerColors[l];
            ctx.stroke();
          }
        } else {
          ctx.beginPath();
          ctx.globalAlpha = 0.15;
          ctx.lineWidth = 1.5;
          ctx.strokeStyle = colRecording;
          ctx.moveTo(0, mid);
          ctx.lineTo(w, mid);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
      if (active) raf = requestAnimationFrame(draw);
    };
    draw();
    return () => {
      cancelAnimationFrame(raf);
      resizeObserver?.disconnect();
    };
  }, [readWaveform, readSpectrum, sampleRate, width, height, active, variant]);

  return <canvas ref={canvasRef} style={{ width: width ?? "100%", height, display: "block", pointerEvents: "none" }} />;
}
