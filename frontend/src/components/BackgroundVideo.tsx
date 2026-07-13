import { useEffect, useRef } from "react";

/** Duration (in seconds) of the fade-in at the start and fade-out at the end. */
const FADE_SECONDS = 0.5;
/** Pause (in ms) after the video ends before it replays from the beginning. */
const REPLAY_DELAY_MS = 100;

interface BackgroundVideoProps {
  src: string;
}

/**
 * BackgroundVideo
 * ---------------
 * A full-bleed looping background video with a custom, JS-controlled fade.
 *
 * The video starts fully transparent (opacity: 0). On every animation frame we
 * look at the playhead and set the opacity:
 *   - first 0.5s            -> fade IN  (0 -> 1)
 *   - last 0.5s before end  -> fade OUT (1 -> 0)
 *   - in between            -> fully visible
 *
 * We do NOT use the native `loop` attribute. Instead, when the video ends we
 * snap opacity back to 0, wait 100ms, then restart from 0 — giving a clean,
 * controlled loop with no flash between iterations.
 */
export function BackgroundVideo({ src }: BackgroundVideoProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const tick = () => {
      const { currentTime, duration } = video;

      if (duration && !Number.isNaN(duration) && duration > FADE_SECONDS * 2) {
        let opacity = 1;
        if (currentTime < FADE_SECONDS) {
          // Fade in at the start.
          opacity = currentTime / FADE_SECONDS;
        } else if (currentTime > duration - FADE_SECONDS) {
          // Fade out near the end.
          opacity = Math.max(0, (duration - currentTime) / FADE_SECONDS);
        }
        video.style.opacity = String(opacity);
      }

      rafRef.current = requestAnimationFrame(tick);
    };

    const handleEnded = () => {
      video.style.opacity = "0";
      window.setTimeout(() => {
        video.currentTime = 0;
        void video.play();
      }, REPLAY_DELAY_MS);
    };

    const play = () => {
      // Autoplay requires the video to be muted (handled on the element below).
      void video.play().catch(() => {
        /* Autoplay may be blocked until user interaction — safe to ignore. */
      });
    };

    const start = () => {
      play();
      if (rafRef.current === null) {
        rafRef.current = requestAnimationFrame(tick);
      }
    };

    const stop = () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      video.pause();
    };

    // Pause playback and the per-frame opacity loop while the tab is hidden;
    // resume both when it becomes visible again (saves CPU/battery).
    const handleVisibility = () => {
      if (document.hidden) stop();
      else start();
    };

    start();
    video.addEventListener("ended", handleEnded);
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      stop();
      video.removeEventListener("ended", handleEnded);
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, []);

  return (
    <video
      ref={videoRef}
      src={src}
      muted
      autoPlay
      playsInline
      preload="metadata"
      className="absolute inset-0 h-full w-full object-cover"
      style={{ opacity: 0 }}
    />
  );
}
