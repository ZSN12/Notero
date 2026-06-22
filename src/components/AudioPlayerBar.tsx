import { forwardRef, useEffect, useRef, useState } from 'react';
import { Play, Pause, Clock } from 'lucide-react';
import { formatDuration } from '@/services/api';

export interface AudioPlayerBarProps {
  src: string | null;
  className?: string;
  onTimeUpdate?: (currentTimeSeconds: number) => void;
  onPlayingChange?: (playing: boolean) => void;
}

const PLAYBACK_RATES = [1, 1.25, 1.5, 2] as const;

export const AudioPlayerBar = forwardRef<HTMLAudioElement, AudioPlayerBarProps>(
  function AudioPlayerBar({ src, className = '', onTimeUpdate, onPlayingChange }, ref) {
    const internalAudioRef = useRef<HTMLAudioElement>(null);
    const audioRef = (ref as React.RefObject<HTMLAudioElement>) || internalAudioRef;

    const [isPlaying, setIsPlaying] = useState(false);
    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [rateIndex, setRateIndex] = useState(0);
    const [isReady, setIsReady] = useState(false);

    const playbackRate = PLAYBACK_RATES[rateIndex];

    useEffect(() => {
      const audio = audioRef.current;
      if (!audio) return;

      setIsReady(false);
      setCurrentTime(0);
      setDuration(0);
      setIsPlaying(false);
      audio.playbackRate = playbackRate;

      const handleLoadedMetadata = () => {
        setDuration(audio.duration || 0);
        setIsReady(true);
      };
      const handleTimeUpdate = () => {
        const t = audio.currentTime || 0;
        setCurrentTime(t);
        onTimeUpdate?.(t);
      };
      const handlePlay = () => {
        setIsPlaying(true);
        onPlayingChange?.(true);
      };
      const handlePause = () => {
        setIsPlaying(false);
        onPlayingChange?.(false);
      };
      const handleEnded = () => {
        setIsPlaying(false);
        onPlayingChange?.(false);
      };

      audio.addEventListener('loadedmetadata', handleLoadedMetadata);
      audio.addEventListener('timeupdate', handleTimeUpdate);
      audio.addEventListener('play', handlePlay);
      audio.addEventListener('pause', handlePause);
      audio.addEventListener('ended', handleEnded);

      // If the element already has metadata loaded (e.g. src unchanged), fire manually.
      if (audio.readyState >= 1) {
        handleLoadedMetadata();
      }

      return () => {
        audio.removeEventListener('loadedmetadata', handleLoadedMetadata);
        audio.removeEventListener('timeupdate', handleTimeUpdate);
        audio.removeEventListener('play', handlePlay);
        audio.removeEventListener('pause', handlePause);
        audio.removeEventListener('ended', handleEnded);
      };
    }, [src, audioRef, onTimeUpdate, onPlayingChange]);

    useEffect(() => {
      const audio = audioRef.current;
      if (!audio) return;
      audio.playbackRate = playbackRate;
    }, [playbackRate, audioRef]);

    const togglePlay = () => {
      const audio = audioRef.current;
      if (!audio || !src) return;
      if (isPlaying) {
        audio.pause();
      } else {
        void audio.play();
      }
    };

    const handleSeek = (value: number) => {
      const audio = audioRef.current;
      if (!audio || !isFinite(value)) return;
      audio.currentTime = value;
      setCurrentTime(value);
    };

    const cycleRate = () => {
      setRateIndex((i) => (i + 1) % PLAYBACK_RATES.length);
    };

    const progress = duration > 0 ? (currentTime / duration) * 100 : 0;
    const disabled = !src || !isReady;

    return (
      <div
        className={`flex items-center gap-3 px-3 py-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl ${className}`}
      >
        <button
          type="button"
          onClick={togglePlay}
          disabled={disabled}
          aria-label={isPlaying ? '暂停' : '播放'}
          className="min-w-[40px] min-h-[40px] rounded-full bg-blue-500 text-white flex items-center justify-center hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isPlaying ? (
            <Pause className="w-4 h-4" />
          ) : (
            <Play className="w-4 h-4 ml-0.5" />
          )}
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Clock className="w-3 h-3 text-blue-600 dark:text-blue-400" />
            <span className="text-xs text-blue-700 dark:text-blue-300 tabular-nums">
              {formatDuration(currentTime * 1000)} / {formatDuration(duration * 1000)}
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={duration || 0}
            step={0.1}
            value={currentTime}
            onChange={(e) => handleSeek(Number(e.target.value))}
            disabled={disabled}
            className="w-full h-1.5 bg-blue-200 dark:bg-blue-800 rounded-lg appearance-none cursor-pointer disabled:cursor-not-allowed accent-blue-600"
            style={{
              backgroundImage: `linear-gradient(to right, #2563eb 0%, #2563eb ${progress}%, #bfdbfe ${progress}%, #bfdbfe 100%)`,
            }}
          />
        </div>

        <button
          type="button"
          onClick={cycleRate}
          disabled={disabled}
          className="min-w-[44px] px-1.5 py-1 text-[10px] font-medium rounded-md bg-white dark:bg-slate-800 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-700 hover:bg-blue-100 dark:hover:bg-blue-900/40 disabled:opacity-50 transition-colors"
          title="播放速度"
        >
          {playbackRate}x
        </button>

        <audio ref={audioRef} src={src ?? undefined} preload="metadata" className="hidden" />
      </div>
    );
  },
);
