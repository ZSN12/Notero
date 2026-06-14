import { request } from './core';
import type { SessionProcessingStatus } from './types';

export async function getSessionProcessingStatus(sessionId: string): Promise<SessionProcessingStatus> {
  return request<SessionProcessingStatus>(`/api/sessions/${sessionId}/processing-status`);
}
