import { useState, useEffect, useCallback, useRef } from 'react';
import { runAllAgents } from '@/services/api';
import type { SessionProcessingStatus } from '@/services/api';

export function useAutoGenerate(
  sessionId: string | undefined,
  processingStatus: SessionProcessingStatus | null,
) {
  const [autoGenerateStudyMaterials, setAutoGenerateStudyMaterials] = useState(() => {
    try {
      const raw = localStorage.getItem('notero_auto_generate_study_materials');
      return raw === null ? true : JSON.parse(raw);
    } catch {
      return true;
    }
  });
  const lastTriggeredSignatureRef = useRef<string | null>(null);
  const [autoGenerateToast, setAutoGenerateToast] = useState<string | null>(null);
  const lastToastSignatureRef = useRef<string | null>(null);
  const toastTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Persist setting
  const persistSetting = useCallback((value: boolean) => {
    localStorage.setItem('notero_auto_generate_study_materials', JSON.stringify(value));
    setAutoGenerateStudyMaterials(value);
  }, []);

  // Cleanup timeouts on unmount
  useEffect(() => {
    return () => {
      if (toastTimeoutRef.current) {
        clearTimeout(toastTimeoutRef.current);
        toastTimeoutRef.current = null;
      }
    };
  }, []);

  const scheduleToastClear = useCallback((duration = 4000) => {
    if (toastTimeoutRef.current) {
      clearTimeout(toastTimeoutRef.current);
    }
    toastTimeoutRef.current = setTimeout(() => {
      setAutoGenerateToast(null);
      toastTimeoutRef.current = null;
    }, duration);
  }, []);

  // Observe processing status and show toast messages for agent stages
  useEffect(() => {
    if (!processingStatus) return;
    const stages = processingStatus.stages;
    const agentStages = [stages.mindmap, stages.quiz_bank];
    const anyRunning = agentStages.some(s => s?.status === 'running');
    const anyActionableError = agentStages.some(s => s?.status === 'error');
    const allSettled = agentStages.every(s => s?.status !== 'running');
    const allReady = agentStages.every(s => s?.status === 'ready' || s?.status === 'idle');
    const hasAgents = agentStages.some(s => s?.status !== 'idle');
    const signature = agentStages.map(s => `${s?.status || 'idle'}:${s?.content_hash || ''}:${s?.error_message || ''}`).join('|');

    const showOnceForSignature = (message: string, duration = 4000) => {
      const toastKey = `${message}|${signature}`;
      if (lastToastSignatureRef.current === toastKey) return undefined;
      lastToastSignatureRef.current = toastKey;
      setAutoGenerateToast(message);
      scheduleToastClear(duration);
      return () => {
        if (toastTimeoutRef.current) {
          clearTimeout(toastTimeoutRef.current);
          toastTimeoutRef.current = null;
        }
      };
    };

    if (anyRunning) {
      setAutoGenerateToast('正在生成学习资料...');
    } else if (allReady && hasAgents) {
      return showOnceForSignature('学习资料生成完成');
    } else if (anyActionableError && hasAgents && allSettled) {
      const failed: string[] = [];
      if (stages.mindmap?.status === 'error') failed.push('导图');
      if (stages.quiz_bank?.status === 'error') failed.push('题库');
      const msg = failed.length === 1
        ? `${failed[0]}生成失败，可手动重试`
        : `${failed.join('、')}生成失败，可手动重试`;
      return showOnceForSignature(msg);
    }
  }, [processingStatus, scheduleToastClear]);

  const handleTriggerAgents = useCallback(async (sid: string | undefined, roles?: string[]) => {
    if (!sid) return;
    try {
      await runAllAgents(sid, roles && roles.length > 0 ? roles : ['mindmap', 'quiz']);
    } catch {
      setAutoGenerateToast('自动启动学习资料生成失败，可手动重试');
      scheduleToastClear(4000);
    }
  }, [scheduleToastClear]);

  // Auto-trigger learning-material agents once after the user uploads audio and
  // the transcript + vector index are ready. Only trigger when both agents are
  // still in an initial/unstarted state. Remember the trigger signature so we
  // don't auto-trigger again until the user deletes the output or resets the
  // stage back to idle.
  useEffect(() => {
    if (!sessionId || !processingStatus || !autoGenerateStudyMaterials) return;
    const stages = processingStatus.stages;
    const mindmapStage = stages.mindmap;
    const quizBankStage = stages.quiz_bank;

    const agentStatus = (s: typeof mindmapStage) => s?.status || 'idle';
    const mindmapStatus = agentStatus(mindmapStage);
    const quizBankStatus = agentStatus(quizBankStage);
    const canAutoStart = ['idle', 'not_generated', 'empty'].includes(mindmapStatus) &&
      ['idle', 'not_generated', 'empty'].includes(quizBankStatus);

    if (!processingStatus.can_auto_generate || !canAutoStart) {
      // If either agent has been reset to idle (e.g. after deletion), clear the
      // signature so a future ready state can auto-trigger again.
      if (mindmapStatus === 'idle' || quizBankStatus === 'idle') {
        lastTriggeredSignatureRef.current = null;
      }
      return;
    }

    const hash = stages.vector_index?.content_hash || stages.transcript_finalize?.content_hash || '';
    const signature = `${sessionId}:${mindmapStatus}:${quizBankStatus}:${hash}`;
    if (hash && lastTriggeredSignatureRef.current !== signature) {
      lastTriggeredSignatureRef.current = signature;
      handleTriggerAgents(sessionId);
    }
  }, [sessionId, processingStatus, autoGenerateStudyMaterials, handleTriggerAgents]);

  return {
    state: { autoGenerateStudyMaterials, autoGenerateToast },
    actions: { setAutoGenerateStudyMaterials: persistSetting, setAutoGenerateToast, handleTriggerAgents },
  };
}
