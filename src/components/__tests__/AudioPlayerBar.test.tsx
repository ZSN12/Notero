import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { createRef } from 'react';
import { AudioPlayerBar } from '../AudioPlayerBar';

describe('AudioPlayerBar', () => {
  const originalPlay = window.HTMLMediaElement.prototype.play;
  const originalPause = window.HTMLMediaElement.prototype.pause;

  beforeEach(() => {
    window.HTMLMediaElement.prototype.play = vi.fn(async () => undefined);
    window.HTMLMediaElement.prototype.pause = vi.fn();
  });

  afterEach(() => {
    window.HTMLMediaElement.prototype.play = originalPlay;
    window.HTMLMediaElement.prototype.pause = originalPause;
  });

  it('renders the play button and time display', () => {
    render(<AudioPlayerBar src="/audio.wav" />);
    expect(screen.getByLabelText('播放')).toBeInTheDocument();
    expect(screen.getByText('00:00:00 / 00:00:00')).toBeInTheDocument();
  });

  it('toggles play/pause when the button is clicked', () => {
    render(<AudioPlayerBar src="/audio.wav" />);
    const audio = document.querySelector('audio') as HTMLAudioElement;
    fireEvent.loadedMetadata(audio);

    const button = screen.getByLabelText('播放');
    fireEvent.click(button);
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled();

    fireEvent.play(audio);
    expect(screen.getByLabelText('暂停')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('暂停'));
    expect(window.HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  });

  it('notifies onPlayingChange when playback state changes', () => {
    const onPlayingChange = vi.fn();
    render(<AudioPlayerBar src="/audio.wav" onPlayingChange={onPlayingChange} />);
    const audio = document.querySelector('audio') as HTMLAudioElement;
    fireEvent.loadedMetadata(audio);

    fireEvent.click(screen.getByLabelText('播放'));
    fireEvent.play(audio);
    expect(onPlayingChange).toHaveBeenCalledWith(true);

    fireEvent.click(screen.getByLabelText('暂停'));
    fireEvent.pause(audio);
    expect(onPlayingChange).toHaveBeenCalledWith(false);
  });

  it('notifies onTimeUpdate as audio currentTime advances', () => {
    const onTimeUpdate = vi.fn();
    const ref = createRef<HTMLAudioElement>();
    render(<AudioPlayerBar ref={ref} src="/audio.wav" onTimeUpdate={onTimeUpdate} />);
    const audio = ref.current!;
    Object.defineProperty(audio, 'duration', { value: 120, configurable: true });
    fireEvent.loadedMetadata(audio);

    Object.defineProperty(audio, 'currentTime', { value: 65, configurable: true });
    fireEvent.timeUpdate(audio);
    expect(onTimeUpdate).toHaveBeenCalledWith(65);
    expect(screen.getByText('00:01:05 / 00:02:00')).toBeInTheDocument();
  });

  it('cycles playback rate when the rate button is clicked', () => {
    render(<AudioPlayerBar src="/audio.wav" />);
    const audio = document.querySelector('audio') as HTMLAudioElement;
    fireEvent.loadedMetadata(audio);

    const rateButton = screen.getByTitle('播放速度');
    expect(rateButton).toHaveTextContent('1x');
    fireEvent.click(rateButton);
    expect(rateButton).toHaveTextContent('1.25x');
    fireEvent.click(rateButton);
    expect(rateButton).toHaveTextContent('1.5x');
    fireEvent.click(rateButton);
    expect(rateButton).toHaveTextContent('2x');
    fireEvent.click(rateButton);
    expect(rateButton).toHaveTextContent('1x');
  });
});
