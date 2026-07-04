/**
 * fluidviz.ts — pure math for the Siri-style fluid audio visualizer.
 * Line variant: a sum of slowly drifting sine harmonics under a raised-cosine
 * envelope (center-weighted lobe). Ring variant: a circle whose radius is
 * modulated by low-order harmonics. Both scale with a gated, smoothed level
 * in [0,1] (level comes from waveform.ts's rms/noise-gate). Zero allocation
 * beyond the caller-provided output arrays.
 */

/** Attack/release smoothing toward `target` — fast rise, slow liquid decay. */
export function smoothLevel(prev: number, target: number, attack = 0.5, release = 0.08): number {
  const a = target > prev ? attack : release;
  return prev + a * (target - prev);
}

/** Raised-cosine window: 0 at both ends, 1 in the middle (the Siri lobe). */
export function envelope(x01: number): number {
  const x = Math.min(1, Math.max(0, x01));
  return 0.5 - 0.5 * Math.cos(2 * Math.PI * x);
}

export interface FluidLayer { freq: number; speed: number; gain: number; }
/** Three drifting harmonics — deliberately few, tuned by eye. */
export const LAYERS: FluidLayer[] = [
  { freq: 1.0, speed: 0.7,  gain: 1.0 },
  { freq: 1.7, speed: -0.5, gain: 0.7 },
  { freq: 2.3, speed: 0.3,  gain: 0.5 },
];

/** Fill `out[0..n-1]` with y-offsets in [-1, 1] for one layer at time t (s). */
export function fluidCurve(n: number, t: number, level: number, layer: FluidLayer, out: number[]): number[] {
  for (let i = 0; i < n; i++) {
    const x = i / (n - 1);
    out[i] = envelope(x) * level * layer.gain *
      Math.sin(2 * Math.PI * (layer.freq * x + layer.speed * t) + layer.freq * 5);
  }
  return out;
}

/** Perceptual level: gate is a cutoff (not a multiplier), then a compressive
 *  power curve so quiet speech still visibly moves the wave.
 *  ponytail: 0.06/0.6 tuned by ear on one mic; expose in DevTuner if a user's
 *  mic ever needs different constants. */
export function perceptualLevel(frameRms: number, floor: number): number {
  if (frameRms <= floor * 1.5) return 0;
  return Math.min(1, Math.pow(frameRms / 0.06, 0.6));
}

/** Split a byte FFT frame into 3 normalized band energies [low, mid, high].
 *  Bands: 0–300 Hz, 300–2000 Hz, 2000–6000 Hz. binHz = sampleRate / fftSize. */
export function bandLevels(spectrum: Uint8Array, sampleRate: number, fftSize: number): [number, number, number] {
  const binHz = sampleRate / fftSize;
  const edges = [0, 300, 2000, 6000];
  const out: [number, number, number] = [0, 0, 0];
  for (let b = 0; b < 3; b++) {
    const from = Math.floor(edges[b] / binHz);
    const to = Math.min(spectrum.length, Math.ceil(edges[b + 1] / binHz));
    let sum = 0;
    for (let i = from; i < to; i++) sum += spectrum[i];
    out[b] = to > from ? sum / ((to - from) * 255) : 0;
  }
  return out;
}

/** Fill `out[0..n-1]` with radius multipliers (~1.0) for the ring variant. */
export function fluidRing(n: number, t: number, level: number, out: number[]): number[] {
  for (let i = 0; i < n; i++) {
    const th = (i / n) * 2 * Math.PI;
    out[i] = 1
      + 0.10 * level * Math.sin(3 * th + t * 2.1)
      + 0.06 * level * Math.sin(5 * th - t * 3.3)
      + 0.04 * level * Math.sin(8 * th + t * 1.7);
  }
  return out;
}
