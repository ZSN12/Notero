import { useState } from 'react';
import { finalizeTranscript } from '@/services/api';
import { transcriptTextFromRawTranscript } from '@/lib/noteLayout';

interface TranscriptEntry {
  correction_stage?: string;
  is_ai_corrected?: boolean;
  correction_error?: string;
}

export function useRestructure() {
  const [isRestructuring, setIsRestructuring] = useState(false);

  const handleRestructure = async (
    sessionId: string | undefined,
    onReceiveAiText: (text: string, options?: { force?: boolean }) => void,
    onCorrectionStatus: (status: { type: 'idle' | 'processing' | 'corrected' | 'local' | 'error'; message?: string }) => void,
    autoGenerate = true,
  ): Promise<boolean> => {
    if (!sessionId) return false;
    setIsRestructuring(true);
    onCorrectionStatus({ type: 'processing', message: '正在 AI 整理...' });
    try {
      // Use unified finalization API (same path as post-upload restructure)
      const result = await finalizeTranscript(sessionId, autoGenerate);
      const note = result?.note;
      if (note?.transcript && note.transcript.length > 0) {
        const dbText = transcriptTextFromRawTranscript(note.transcript);
        if (dbText) {
          onReceiveAiText(dbText, { force: true });
        }
        // Determine correction status from the latest authoritative entry only.
        let latest: TranscriptEntry | undefined;
        for (const entry of note.transcript as TranscriptEntry[]) {
          if (entry && (entry.correction_stage === 'final' || entry.correction_stage === 'user_edited')) {
            latest = entry;
          }
        }
        if (latest?.is_ai_corrected) {
          onCorrectionStatus({ type: 'corrected' });
        } else if (latest?.correction_error) {
          onCorrectionStatus({ type: 'error', message: latest.correction_error });
        } else {
          onCorrectionStatus({ type: 'local' });
        }
      }
      return true;
    } catch (err: unknown) {
      console.error('Restructure failed:', err);
      onCorrectionStatus({ type: 'error', message: err instanceof Error ? err.message : '整理失败' });
      return false;
    } finally {
      setIsRestructuring(false);
    }
  };

  return {
    state: { isRestructuring },
    actions: { handleRestructure },
  };
}
