import { useState, useRef, useCallback, useEffect } from 'react';
import { ASRWebSocketClient } from '@/services/asrWebSocket';
import { finishRecording, getAudioUrl, updateSessionDuration, fetchNote } from '@/services/api';

export function useRecording(
  sessionId: string | undefined,
  options?: { onFinalize?: () => void },
) {
  const [isRecording, setIsRecording] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const isPausedRef = useRef(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isError, setIsError] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const [currentTime, setCurrentTime] = useState('00:00:00');
  const [waveHeights, setWaveHeights] = useState<number[]>(Array(60).fill(4));
  const [audioPlaybackUrl, setAudioPlaybackUrl] = useState<string | null>(null);
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);

  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const startTimeRef = useRef<number>(0);
  const pausedDurationRef = useRef<number>(0);
  const pauseStartTimeRef = useRef<number>(0);
  const timerIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const audioPlayerRef = useRef<HTMLAudioElement | null>(null);

  const wsClientRef = useRef<ASRWebSocketClient | null>(null);
  const audioWorkletRef = useRef<AudioWorkletNode | null>(null);
  const scriptProcessorRef = useRef<ScriptProcessorNode | null>(null);

  const formatTime = useCallback((totalMs: number) => {
    const totalSeconds = Math.floor(totalMs / 1000);
    const hh = Math.floor(totalSeconds / 3600);
    const mm = Math.floor((totalSeconds % 3600) / 60);
    const ss = totalSeconds % 60;
    return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
  }, []);

  const floatToInt16 = useCallback((floatArray: Float32Array): Int16Array => {
    const int16 = new Int16Array(floatArray.length);
    for (let i = 0; i < floatArray.length; i++) {
      const s = Math.max(-1, Math.min(1, floatArray[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16;
  }, []);

  const updateWaveform = useCallback(() => {
    if (!analyserRef.current) return;
    const analyser = analyserRef.current;
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(dataArray);
    const newHeights = Array.from({ length: 60 }, (_, i) => {
      const dataIndex = Math.floor((i / 60) * analyser.frequencyBinCount);
      const value = dataArray[dataIndex] || 0;
      return Math.max(4, (value / 255) * 28);
    });
    setWaveHeights(newHeights);
    animationFrameRef.current = requestAnimationFrame(updateWaveform);
  }, []);

  const _cleanupTimers = useCallback(() => {
    if (timerIntervalRef.current) { clearInterval(timerIntervalRef.current); timerIntervalRef.current = null; }
    if (animationFrameRef.current) { cancelAnimationFrame(animationFrameRef.current); animationFrameRef.current = null; }
  }, []);

  const _startTimerOnly = useCallback(() => {
    timerIntervalRef.current = setInterval(() => {
      if (!isPausedRef.current)
        setCurrentTime(formatTime(Date.now() - startTimeRef.current - pausedDurationRef.current));
    }, 200);
    animationFrameRef.current = requestAnimationFrame(updateWaveform);
  }, [formatTime, updateWaveform]);

  const startRecording = useCallback(async (
    onPartial: (text: string) => void,
    onFinal: (text: string) => void,
  ) => {
    if (!sessionId) return;
    setIsError(false);
    setErrorMessage('');
    setIsProcessing(true);

    try {
      // 1. Get mic stream
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      // 2. Setup AudioContext @ 16kHz
      let audioContext: AudioContext;
      try {
        audioContext = new AudioContext({ sampleRate: 16000 });
      } catch {
        audioContext = new AudioContext();
      }
      audioContextRef.current = audioContext;

      // 3. Setup WebSocket
      const wsClient = new ASRWebSocketClient(sessionId, {
        onPartial: (text) => onPartial(text),
        onFinal: (text) => onFinal(text),
        onStatus: () => { /* optional */ },
        onError: (detail) => {
          setIsError(true);
          setErrorMessage(detail);
        },
        onDone: () => { /* handled by stopRecording */ },
      });
      await wsClient.connect();
      wsClientRef.current = wsClient;

      // 4. Setup audio processing
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      analyserRef.current = analyser;

      // Try AudioWorklet first, fallback to ScriptProcessorNode
      try {
        await audioContext.audioWorklet.addModule('/pcm-processor.js');
        const worklet = new AudioWorkletNode(audioContext, 'pcm-processor', {
          processorOptions: { bufferSize: 2560 }, // ~160ms @ 16kHz
        });
        worklet.port.onmessage = (e) => {
          if (!isPausedRef.current && wsClientRef.current) {
            const int16 = floatToInt16(e.data);
            wsClientRef.current.sendAudioFrame(int16);
          }
        };
        source.connect(worklet);
        audioWorkletRef.current = worklet;
      } catch {
        // Fallback: ScriptProcessorNode
        const processor = audioContext.createScriptProcessor(4096, 1, 1);
        processor.onaudioprocess = (e) => {
          if (isPausedRef.current) return;
          const floatData = e.inputBuffer.getChannelData(0);
          const int16 = floatToInt16(floatData);
          wsClient.sendAudioFrame(int16);
        };
        source.connect(processor);
        // Keep the node in the audio graph so it processes, but mute the output
        // to prevent the microphone from being played back through the speakers.
        const muteGain = audioContext.createGain();
        muteGain.gain.value = 0;
        processor.connect(muteGain);
        muteGain.connect(audioContext.destination);
        scriptProcessorRef.current = processor;
      }

      // 5. Start waveform + timer
      startTimeRef.current = Date.now();
      pausedDurationRef.current = 0;
      pauseStartTimeRef.current = 0;
      isPausedRef.current = false;

      _startTimerOnly();

      setIsRecording(true);
      setIsPaused(false);
      setIsProcessing(false);
    } catch (error: any) {
      console.error('Recording failed:', error);
      setIsProcessing(false);
      setIsError(true);
      if (error.name === 'NotAllowedError') {
        setErrorMessage('麦克风权限被拒绝。请在浏览器设置中允许访问麦克风，然后重试。');
      } else if (error.name === 'NotFoundError') {
        setErrorMessage('未检测到麦克风设备。请连接麦克风后重试。');
      } else {
        setErrorMessage('录音启动失败，请检查设备并重试。');
      }
    }
  }, [sessionId, floatToInt16, _startTimerOnly]);

  const pauseRecording = useCallback(() => {
    isPausedRef.current = true;
    wsClientRef.current?.pause();
    pauseStartTimeRef.current = Date.now();
    _cleanupTimers();
    setIsPaused(true);
    setWaveHeights(Array(60).fill(4));
  }, [_cleanupTimers]);

  const resumeRecording = useCallback(() => {
    isPausedRef.current = false;
    if (pauseStartTimeRef.current > 0) {
      pausedDurationRef.current += Date.now() - pauseStartTimeRef.current;
      pauseStartTimeRef.current = 0;
    }
    wsClientRef.current?.resume();
    _startTimerOnly();
    setIsPaused(false);
  }, [_startTimerOnly]);

  const stopRecording = useCallback(async (onTranscriptUpdate: (text: string, options?: { force?: boolean; authoritative?: boolean }) => void): Promise<{ note?: any; status?: string } | undefined> => {
    // 1. Cleanup audio
    if (streamRef.current) { streamRef.current.getTracks().forEach((track) => track.stop()); streamRef.current = null; }
    if (audioContextRef.current) { await audioContextRef.current.close(); audioContextRef.current = null; }
    _cleanupTimers();

    // 2. Stop WebSocket gracefully
    setIsRecording(false);
    setIsPaused(false);
    setIsProcessing(true);
    setWaveHeights(Array(60).fill(4));

    try {
      if (wsClientRef.current) {
        await wsClientRef.current.end();
        wsClientRef.current.close();
        wsClientRef.current = null;
      }

      // 3. Update session duration
      if (sessionId && startTimeRef.current) {
        await updateSessionDuration(sessionId, Date.now() - startTimeRef.current - pausedDurationRef.current);
      }

      // 4. Call audio-finish: concatenate and persist audio only. AI organization
      // remains an explicit user action for real-time recordings.
      let finalNote: any = undefined;
      let finishStatus: string | undefined = undefined;
      if (sessionId) {
        const finishResult = await finishRecording(sessionId);
        finishStatus = finishResult.status;
        finalNote = finishResult.note;
        if (finishResult.status === 'error') {
          setIsError(true);
          setErrorMessage('录音保存失败，请稍后重试');
        } else {
          // Refresh processing status so the UI can offer the AI organize action.
          options?.onFinalize?.();
          if (finalNote?.transcript && finalNote.transcript.length > 0) {
            const sorted = [...finalNote.transcript].sort(
              (a: any, b: any) => (a.chunk_index || 0) - (b.chunk_index || 0)
            );
            const hasFinalTranscript = sorted.some((c: any) => c.correction_stage === 'final');
            if (hasFinalTranscript) {
              const dbText = sorted
                .map((c: any) => c.display_text || c.corrected_text || c.text || c.raw_text || '')
                .filter(Boolean)
                .join('\n\n')
                .trim();
              if (dbText && dbText.length > 0) {
                onTranscriptUpdate(dbText, { authoritative: true });
              }
            }
          }
        }
        setAudioPlaybackUrl(getAudioUrl(sessionId));
      }
      return { note: finalNote, status: finishStatus };
    } catch (error: any) {
      console.error('Failed to finish recording:', error);
      setIsError(true);
      setErrorMessage(error?.message || '录音收尾失败，请稍后重试');
    } finally {
      setIsProcessing(false);
    }
  }, [sessionId, _cleanupTimers, options]);

  useEffect(() => {
    return () => {
      if (streamRef.current) streamRef.current.getTracks().forEach((track) => track.stop());
      if (audioContextRef.current) audioContextRef.current.close();
      _cleanupTimers();
      wsClientRef.current?.close();
      wsClientRef.current = null;
    };
  }, [_cleanupTimers]);

  return {
    state: {
      isRecording,
      isPaused,
      isProcessing,
      isError,
      errorMessage,
      currentTime,
      waveHeights,
      audioPlaybackUrl,
      isPlayingAudio,
    },
    refs: {
      audioPlayerRef,
    },
    actions: {
      startRecording,
      pauseRecording,
      resumeRecording,
      stopRecording,
      setIsError,
      setErrorMessage,
      setIsProcessing,
      setIsPlayingAudio,
      setAudioPlaybackUrl,
    },
  };
}
