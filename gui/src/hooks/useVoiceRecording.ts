import { useCallback, useEffect, useRef, useState } from "react";
import { MicRecorder } from "../lib/recorder";
import { shouldAutoStop } from "../lib/voiceLimits";
import { logger } from "../lib/logger";

export type VoicePhase = "idle" | "recording" | "sending";

export function useVoiceRecording(captureAudio: (b64: string) => void) {
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [elapsedMs, setElapsedMs] = useState(0);
  const recRef = useRef<MicRecorder | null>(null);
  const rafRef = useRef(0);

  const stopTicking = useCallback(() => cancelAnimationFrame(rafRef.current), []);

  const finish = useCallback(async () => {
    const rec = recRef.current;
    if (!rec) return;
    stopTicking();
    setPhase("sending");
    try {
      const { b64 } = await rec.stop();
      captureAudio(b64);
    } catch (err) {
      logger.error("voice", "stop/encode failed", err);
    } finally {
      recRef.current = null;
      setPhase("idle");
      setElapsedMs(0);
    }
  }, [captureAudio, stopTicking]);

  const toggle = useCallback(async () => {
    if (phase === "sending") return;
    if (phase === "recording") { void finish(); return; }
    const rec = new MicRecorder();
    try {
      await rec.start();
    } catch (err) {
      logger.error("voice", "mic permission/start failed", err);
      return; // A6 wires a toast for this
    }
    recRef.current = rec;
    setPhase("recording");
    const tick = () => {
      const ms = rec.elapsedMs;
      setElapsedMs(ms);
      if (shouldAutoStop(ms)) { void finish(); return; }
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
  }, [phase, finish]);

  const cancel = useCallback(() => {
    stopTicking();
    recRef.current?.cancel();
    recRef.current = null;
    setPhase("idle");
    setElapsedMs(0);
  }, [stopTicking]);

  const readWaveform = useCallback((out: Float32Array) => { recRef.current?.readWaveform(out); }, []);
  const readSpectrum = useCallback((out: Uint8Array) => { recRef.current?.readSpectrum(out); }, []);
  const sampleRate = recRef.current?.sampleRate ?? 48000;

  useEffect(() => () => { recRef.current?.cancel(); stopTicking(); }, [stopTicking]);

  return { phase, elapsedMs, toggle, cancel, readWaveform, readSpectrum, sampleRate };
}
