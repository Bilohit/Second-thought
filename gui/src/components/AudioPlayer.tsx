import { useRef, useState } from "react";
import { formatClock } from "../lib/audioPlayerFormat";
import { PlayIcon, PauseIcon } from "./PillMenu/icons";

const WAVE_BAR_COUNT = 24;
const WAVE_HEIGHTS = [6, 10, 16, 20, 14, 8, 12, 18, 22, 16, 10, 7, 13, 19, 23, 17, 11, 8, 14, 20, 15, 9, 6, 5];

export function AudioPlayer({ src }: { src: string }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);

  const progress = duration > 0 ? currentTime / duration : 0;
  const playedBars = Math.round(progress * WAVE_BAR_COUNT);

  const toggle = () => {
    const el = audioRef.current;
    if (!el) return;
    if (playing) {
      el.pause();
    } else {
      if (duration > 0 && currentTime >= duration) el.currentTime = 0;
      void el.play();
    }
  };

  return (
    <div className="audio-player">
      <audio
        ref={audioRef}
        src={src}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => {
          // webm/opus (MediaRecorder output, see recorder.ts) often reports
          // duration as Infinity until more of the stream has been read --
          // an unguarded assignment here poisons formatClock() and the
          // progress bar (duration > 0 comparisons never resolve sanely).
          // Ignore non-finite readings; a later timeupdate-driven duration
          // fix-up isn't needed since the fallback clock below covers it.
          const d = e.currentTarget.duration;
          if (Number.isFinite(d)) setDuration(d);
        }}
        onEnded={() => setPlaying(false)}
      />
      <button
        type="button"
        className="audio-player__play"
        aria-label={playing ? "Pause" : "Play"}
        onClick={toggle}
      >
        {playing ? <PauseIcon size={14} /> : <PlayIcon size={14} />}
      </button>
      <div className="audio-player__wave" aria-hidden="true">
        {WAVE_HEIGHTS.map((h, i) => (
          <div
            key={i}
            className={`audio-player__bar${i < playedBars ? " audio-player__bar--played" : ""}`}
            style={{ height: `${h}px` }}
          />
        ))}
      </div>
      <span className="audio-player__time">
        {formatClock(currentTime)}/{duration > 0 ? formatClock(duration) : "--:--"}
      </span>
    </div>
  );
}
