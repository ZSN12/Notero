import { useState, useEffect, useCallback, useRef } from 'react';
import { runAllAgents } from '@/services/api';
import type { SessionProcessingStatus } from '@/services/api';

export function useAutoGenerate(
  sessionId: string | undefined,
  processingStatus: SessionProcessingStatus | null,
  refresh: () => Promise<void> = async () => {},
) {
  const [autoGenerateStudyMaterials, setAutoGenerateStudyMaterials] = useState(() => {
    try {
      const raw = localStorage.getItem('notero_auto_generate_study_materials');
      return raw === null ? true : JSON.parse(raw);
    } catch {
      return true;
    }
  });
  const [autoGenerateToast, setAutoGenerateToast] = useState<string | null>(null);
  const [isTriggeringAgents, setIsTriggeringAgents] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);
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

  const clearToastTimeout = useCallback(() => {
    if (toastTimeoutRef.current) {
      clearTimeout(toastTimeoutRef.current);
      toastTimeoutRef.current = null;
    }
  }, []);

  const scheduleToastClear = useCallback((duration = 4000) => {
    clearToastTimeout();
    toastTimeoutRef.current = setTimeout(() => {
      setAutoGenerateToast(null);
      toastTimeoutRef.current = null;
    }, duration);
  }, [clearToastTimeout]);

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
    };

    if (anyRunning) {
      clearToastTimeout();
      const runningMessage = stages.mindmap?.status === 'running' && stages.quiz_bank?.status === 'running'
        ? '正在生成知识导图和题库...'
        : stages.mindmap?.status === 'running'
          ? '正在生成知识导图...'
          : '正在生成题库...';
      lastToastSignatureRef.current = `running|${signature}`;
      setAutoGenerateToast(current => current === runningMessage ? current : runningMessage);
      return undefined;
    } else if (allReady && hasAgents) {
      showOnceForSignature('学习资料生成完成');
    } else if (anyActionableError && hasAgents && allSettled) {
      const failed: string[] = [];
      if (stages.mindmap?.status === 'error') failed.push('导图');
      if (stages.quiz_bank?.status === 'error') failed.push('题库');
      const msg = failed.length === 1
        ? `${failed[0]}生成失败，可手动重试`
        : `${failed.join('、')}生成失败，可手动重试`;
      showOnceForSignature(msg);
    }
  }, [clearToastTimeout, processingStatus, scheduleToastClear]);

  const handleTriggerAgents = useCallback(async (sid: string | undefined, roles?: string[], force = false) => {
    if (!sid) return;
    const targetRoles = roles && roles.length > 0 ? roles : ['mindmap', 'quiz'];
    const includesMindmap = targetRoles.includes('mindmap');
    const includesQuiz = targetRoles.includes('quiz');
    const startingMessage = includesMindmap && includesQuiz
      ? '正在重新生成知识导图和题库...'
      : includesMindmap
        ? '正在重新生成知识导图...'
        : includesQuiz
          ? '正在重新生成题库...'
          : '正在重新生成学习资料...';
    setIsTriggeringAgents(true);
    setTriggerError(null);
    setAutoGenerateToast(startingMessage);
    try {
      await runAllAgents(sid, targetRoles, force);
      setTriggerError(null);
      await refresh();
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '启动生成失败';
      setTriggerError(msg);
      setAutoGenerateToast(msg);
      scheduleToastClear(4000);
      console.error('handleTriggerAgents failed', err);
    } finally {
      setIsTriggeringAgents(false);
    }
  }, [refresh, scheduleToastClear]);

  return {
    state: { autoGenerateStudyMaterials, autoGenerateToast, isTriggeringAgents, triggerError },
    actions: { setAutoGenerateStudyMaterials: persistSetting, setAutoGenerateToast, handleTriggerAgents },
  };
}
