// gui/src/lib/recorder.ts
/**
 * recorder.ts — MediaRecorder + AnalyserNode wrapper for voice capture.
 * Noise handling: browser-native noiseSuppression/echoCancellation on the
 * input track (zero-latency, done in the audio stack), plus an 85 Hz
 * high-pass before the analyser so rumble never reaches the waveform.
 * Untested by design: browser-API glue; logic is in waveform.ts (tested).
 */
export interface RecordingResult { b64: string; mimeType: string; durationMs: number; }

export class MicRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private chunks: Blob[] = [];
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private startedAt = 0;

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : "";
    this.recorder = new MediaRecorder(this.stream, mime ? { mimeType: mime } : undefined);
    this.chunks = [];
    this.recorder.ondataavailable = (e) => { if (e.data.size > 0) this.chunks.push(e.data); };
    this.ctx = new AudioContext();
    const source = this.ctx.createMediaStreamSource(this.stream);
    const highpass = this.ctx.createBiquadFilter();
    highpass.type = "highpass";
    highpass.frequency.value = 85; // below male fundamental; kills desk/HVAC rumble
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    source.connect(highpass);
    highpass.connect(this.analyser);
    this.recorder.start(250); // 250ms timeslice: a crash loses at most 250ms
    this.startedAt = performance.now();
  }

  /** Fill `out` (length <= fftSize) with the current time-domain frame (-1..1). No-op when idle. */
  readWaveform(out: Float32Array): void {
    // Cast: newer lib.dom types Float32Array as generic over its buffer; getFloatTimeDomainData wants Float32Array<ArrayBuffer>.
    this.analyser?.getFloatTimeDomainData(out as Float32Array<ArrayBuffer>);
  }

  /** Fill `out` (length <= frequencyBinCount) with the current byte FFT frame. No-op when idle. */
  readSpectrum(out: Uint8Array): void {
    this.analyser?.getByteFrequencyData(out as Uint8Array<ArrayBuffer>);
  }

  get sampleRate(): number { return this.ctx?.sampleRate ?? 48000; }

  get elapsedMs(): number { return this.recorder ? performance.now() - this.startedAt : 0; }

  async stop(): Promise<RecordingResult> {
    const recorder = this.recorder;
    if (!recorder) throw new Error("not recording");
    const stopped = new Promise<void>((res) => { recorder.onstop = () => res(); });
    recorder.stop();
    await stopped;
    const blob = new Blob(this.chunks, { type: recorder.mimeType || "audio/webm" });
    const durationMs = performance.now() - this.startedAt;
    this.teardown();
    const buf = new Uint8Array(await blob.arrayBuffer());
    let bin = "";
    for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    return { b64: btoa(bin), mimeType: blob.type, durationMs };
  }

  cancel(): void {
    try { this.recorder?.stop(); } catch { /* already stopped */ }
    this.teardown();
  }

  private teardown(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close().catch(() => {});
    this.recorder = null; this.stream = null; this.ctx = null; this.analyser = null;
    this.chunks = [];
  }
}
