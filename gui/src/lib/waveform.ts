/**
 * waveform.ts — pure math for the voice-recording oscilloscope line.
 *
 * The capsule waveform is the raw time-domain signal (a real scope trace),
 * gated by an adaptive noise floor so it only moves when the user speaks:
 * background hiss keeps frame RMS near the floor -> gain 0 -> flat line.
 * All functions are per-frame O(n) with zero allocation beyond the output
 * array — low-latency by construction.
 */

export function rms(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
  return Math.sqrt(sum / samples.length);
}

/** Adaptive noise floor: rises slowly (EMA a=0.05) when the frame is quiet,
 *  is effectively held during loud frames (a=0.005) so speech never inflates it. */
export function updateNoiseFloor(floor: number, frameRms: number): number {
  const alpha = frameRms < floor * 2 ? 0.05 : 0.005;
  return floor + alpha * (frameRms - floor);
}

/** Soft-knee gate: closed <= floor*1.5, fully open >= floor*4, linear between.
 *  ponytail: fixed 1.5x/4x knee; expose in config if a user's mic needs tuning. */
export function gateGain(frameRms: number, floor: number): number {
  const lo = floor * 1.5;
  const hi = floor * 4;
  if (frameRms <= lo) return 0;
  if (frameRms >= hi) return 1;
  return (frameRms - lo) / (hi - lo);
}

/** n evenly spaced raw samples (sign preserved — this IS the signal). */
export function resamplePolyline(samples: Float32Array, n: number): number[] {
  if (n <= 0 || samples.length === 0) return [];
  const out = new Array<number>(n);
  for (let i = 0; i < n; i++) {
    out[i] = samples[Math.floor((i / n) * samples.length)];
  }
  return out;
}
