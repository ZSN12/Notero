import { useState } from 'react';
import { finalizeTranscript } from '@/services/api';

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
        const sorted = [...note.transcript].sort((a: { chunk_index?: number }, b: { chunk_index?: number }) => (a.chunk_index || 0) - (b.chunk_index || 0));
        const lastEntry = sorted[sorted.length - 1] as { is_ai_corrected?: boolean; correction_error?: string } | undefined;
        const dbText = sorted
          .map((c: { display_text?: string; corrected_text?: string; text?: string }) => c.display_text || c.corrected_text || c.text || '')
          .filter(Boolean)
          .join('\n\n')
          .trim();
        if (dbText) {
          onReceiveAiText(dbText, { force: true });
        }
        if (lastEntry?.is_ai_corrected) {
          onCorrectionStatus({ type: 'corrected' });
        } else if (lastEntry?.correction_error) {
          onCorrectionStatus({ type: 'error', message: lastEntry.correction_error });
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
