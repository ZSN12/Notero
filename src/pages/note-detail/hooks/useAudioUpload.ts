import { useState, useRef, useEffect } from 'react';
import { uploadAudio, finalizeTranscript } from '@/services/api';
import type { BackendNote } from '@/services/api';

export interface AudioUploadCallbacks {
  clearDerivedTranscriptViews: () => void;
  clearStreamingTranscriptChunks: () => void;
  updateTranscriptText: (text: string, append: boolean) => void;
  appendTranscriptText: (text: string, skipDedup?: boolean) => void;
  receiveAiText: (text: string, options?: { force?: boolean }) => void;
  clearStreamingTranscriptChunksFinal: () => void;
  clearContentBlocks: () => void;
  scrollToBottom: () => void;
}

const UPLOAD_STALL_TIMEOUT_MS = 30000; // 30s without any SSE event = stall

const isPendingCorrectionMessage = (message?: string | null) => {
  if (!message) return false;
  return message.includes('等待统一 AI 整理') || message.includes('正在统一 AI 整理');
};

export function useAudioUpload(
  sessionId: string | undefined,
  options?: { onFinalize?: () => void },
) {
  const [isUploadingAudio, setIsUploadingAudio] = useState(false);
  const [audioUploadStatus, setAudioUploadStatus] = useState<string | null>(null);
  const [audioUploadError, setAudioUploadError] = useState<string | null>(null);
  const [audioQueueProgress, setAudioQueueProgress] = useState<{ current: number; total: number } | null>(null);
  const [uploadPhase, setUploadPhase] = useState<'uploading' | 'transcribing' | 'finalizing'>('uploading');
  const audioInputRef = useRef<HTMLInputElement>(null);
  const audioUploadAbortRef = useRef<(() => void) | null>(null);
  const lastSseAtRef = useRef<number>(0);
  const stallTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const queueAbortRef = useRef(false);

  const clearStallTimer = () => {
    if (stallTimerRef.current) {
      clearTimeout(stallTimerRef.current);
      stallTimerRef.current = null;
    }
  };

  const startStallTimer = (abort: () => void) => {
    clearStallTimer();
    lastSseAtRef.current = Date.now();
    stallTimerRef.current = setTimeout(() => {
      const elapsed = Date.now() - lastSseAtRef.current;
      if (elapsed >= UPLOAD_STALL_TIMEOUT_MS) {
        abort();
        setIsUploadingAudio(false);
        setAudioUploadError('上传处理超时，请检查网络或稍后重试');
        setAudioUploadStatus(null);
        audioUploadAbortRef.current = null;
      }
    }, UPLOAD_STALL_TIMEOUT_MS);
  };

  useEffect(() => {
    return () => clearStallTimer();
  }, []);

  const handleAudioUpload = async (
    files: File | File[],
    callbacks: AudioUploadCallbacks,
    onCorrectionStatus: (status: { type: 'idle' | 'processing' | 'corrected' | 'local' | 'error'; message?: string }) => void,
    onTranscriptReady?: (note: BackendNote) => void | Promise<void>,
  ) => {
    if (!sessionId) return;
    const fileArray = Array.isArray(files) ? files : [files];
    if (fileArray.length === 0) return;

    setIsUploadingAudio(true);
    setAudioUploadError(null);
    queueAbortRef.current = false;

    for (let i = 0; i < fileArray.length; i++) {
      if (queueAbortRef.current) break;

      const file = fileArray[i];
      const isFirstFile = i === 0;
      setUploadPhase('uploading');
      setAudioQueueProgress({ current: i + 1, total: fileArray.length });
      setAudioUploadStatus(`正在上传录音文件 (${i + 1}/${fileArray.length})`);
      if (isFirstFile) {
        onCorrectionStatus({ type: 'idle' });
        callbacks.clearDerivedTranscriptViews();
        callbacks.clearStreamingTranscriptChunks();
        callbacks.clearContentBlocks();
        callbacks.updateTranscriptText('', false);
      } else {
        // Insert a light separator between files so user can see new content arriving
        callbacks.appendTranscriptText(`\n─── 录音 ${i + 1} ───\n`, true);
      }

      try {
        await new Promise<void>((resolve, reject) => {
          const { abort } = uploadAudio(file, sessionId, {
            onStart: () => {
              setUploadPhase('transcribing');
            },
            onStatus: (message, segment, total) => {
              lastSseAtRef.current = Date.now();
              if (message) setAudioUploadStatus(`${message} (${i + 1}/${fileArray.length})`);
              else if (segment && total) setAudioUploadStatus(`正在识别第 ${segment}/${total} 段 (${i + 1}/${fileArray.length})`);
            },
            onChunk: (text, _segment, _total, meta) => {
              lastSseAtRef.current = Date.now();
              setAudioUploadStatus(`正在写入转写结果 (${i + 1}/${fileArray.length})`);
              if (text?.trim()) {
                callbacks.appendTranscriptText(text.trim(), true);
                callbacks.scrollToBottom();
              }
              if (meta?.correctionError && !isPendingCorrectionMessage(meta.correctionError)) {
                setAudioUploadStatus(meta.correctionError);
                onCorrectionStatus({ type: 'error', message: meta.correctionError });
              } else if (meta?.isAiCorrected) {
                onCorrectionStatus({ type: 'corrected' });
              }
            },
            onDone: async (note) => {
              clearStallTimer();
              if (note) {
                const sorted = Array.isArray(note.transcript)
                  ? [...note.transcript].sort((a: { chunk_index?: number }, b: { chunk_index?: number }) => (a.chunk_index || 0) - (b.chunk_index || 0))
                  : [];
                const lastEntry = sorted[sorted.length - 1] as { is_ai_corrected?: boolean; correction_error?: string } | undefined;
                if (lastEntry?.is_ai_corrected) {
                  onCorrectionStatus({ type: 'corrected' });
                } else if (lastEntry?.correction_error && !isPendingCorrectionMessage(lastEntry.correction_error)) {
                  onCorrectionStatus({ type: 'error', message: lastEntry.correction_error });
                } else {
                  onCorrectionStatus({ type: 'local' });
                }
              }
              resolve();
            },
            onError: (message) => {
              clearStallTimer();
              setAudioUploadError(message);
              reject(new Error(message));
            },
          });

          audioUploadAbortRef.current = () => {
            queueAbortRef.current = true;
            abort();
          };
          startStallTimer(() => {
            queueAbortRef.current = true;
            abort();
          });
        });
      } catch (err: any) {
        // 某个文件出错，停止后续队列
        setIsUploadingAudio(false);
        setAudioUploadStatus(null);
        setAudioQueueProgress(null);
        setUploadPhase('uploading');
        audioUploadAbortRef.current = null;
        if (audioInputRef.current) audioInputRef.current.value = '';
        return;
      }
    }

    // All files uploaded. Run unified DeepSeek restructure.
    if (!queueAbortRef.current && sessionId) {
      try {
        setUploadPhase('finalizing');
        setAudioUploadStatus('正在统一 AI 整理全部转写...');
        onCorrectionStatus({ type: 'processing', message: '正在统一 AI 整理全部转写...' });
        const finalResult = await finalizeTranscript(sessionId);
        const finalNote = finalResult?.note;
        if (finalNote?.transcript && Array.isArray(finalNote.transcript)) {
          const dbText = finalNote.transcript
            .map((c: any) => c.display_text || c.corrected_text || c.text || c.raw_text || '')
            .filter(Boolean)
            .join('\n\n')
            .trim();
          if (dbText) {
            // Respect user edits made during upload: receiveAiText will queue the
            // AI-restructured version as pending instead of overwriting local changes.
            callbacks.receiveAiText(dbText);
          }
          const lastEntry = finalNote.transcript[finalNote.transcript.length - 1] as any;
          if (lastEntry?.is_ai_corrected) {
            onCorrectionStatus({ type: 'corrected' });
          } else if (lastEntry?.correction_error && !isPendingCorrectionMessage(lastEntry.correction_error)) {
            onCorrectionStatus({ type: 'error', message: lastEntry.correction_error });
          } else {
            onCorrectionStatus({ type: 'local' });
          }
        }
        await onTranscriptReady?.(finalNote);
        options?.onFinalize?.();
      } catch (err: any) {
        const message = err?.message || '统一整理失败';
        setAudioUploadError(message);
        onCorrectionStatus({ type: 'error', message });
      } finally {
        options?.onFinalize?.();
      }
    }

    setIsUploadingAudio(false);
    setAudioUploadStatus(null);
    setAudioQueueProgress(null);
    setUploadPhase('uploading');
    callbacks.clearStreamingTranscriptChunksFinal();
    if (audioInputRef.current) audioInputRef.current.value = '';
    audioUploadAbortRef.current = null;
  };

  return {
    state: { isUploadingAudio, audioUploadStatus, audioUploadError, audioQueueProgress, uploadPhase },
    refs: { audioInputRef, audioUploadAbortRef },
    actions: { handleAudioUpload, setAudioUploadStatus, setAudioUploadError, setIsUploadingAudio, setUploadPhase },
  };
}
