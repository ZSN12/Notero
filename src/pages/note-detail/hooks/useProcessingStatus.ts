import { useState, useEffect, useCallback, useRef } from 'react';
import { getSessionProcessingStatus, SessionProcessingStatus } from '@/services/api';

const POLL_INTERVAL_IDLE = 8000;
const POLL_INTERVAL_RUNNING = 2000;

export function useProcessingStatus(sessionId: string | undefined) {
  const [processingStatus, setProcessingStatus] = useState<SessionProcessingStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchStatus = useCallback(async () => {
    if (!sessionId) return;
    try {
      const status = await getSessionProcessingStatus(sessionId);
      setProcessingStatus(status);
    } catch {
      // silently ignore polling errors
    } finally {
      setIsLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    fetchStatus();

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [sessionId, fetchStatus]);

  useEffect(() => {
    if (!sessionId) return;

    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }

    const isRunning = processingStatus?.overall_status === 'running';
    const interval = isRunning ? POLL_INTERVAL_RUNNING : POLL_INTERVAL_IDLE;

    intervalRef.current = setInterval(() => {
      fetchStatus();
    }, interval);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [sessionId, processingStatus?.overall_status, fetchStatus]);

  const refresh = useCallback(async () => {
    await fetchStatus();
  }, [fetchStatus]);

  return {
    processingStatus,
    isLoading,
    refresh,
  };
}
