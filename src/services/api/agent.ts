import { request } from './core';
import type { AgentTask, BackendNote } from './types';

export interface RestructureTranscriptResult {
  note: BackendNote;
  agents: { session_id: string; agents?: Array<{ role: string; task_id: string; status: string }>; reused?: boolean } | null;
}

export async function runAllAgents(
  sessionId: string,
  roles?: string[],
  force = false,
): Promise<{ workflow_id: string; session_id: string; agents: Array<{ role: string; task_id: string; status: string; progress: number; error: string | null }>; reused?: boolean }> {
  return request(`/api/agents/session/${sessionId}/run`, {
    method: 'POST',
    body: JSON.stringify({ roles, force }),
    timeoutMs: 15000,
  });
}

export async function getAgentTasks(sessionId: string): Promise<{ session_id: string; agents: AgentTask[] }> {
  return request(`/api/agents/session/${sessionId}/tasks`, { timeoutMs: 15000 });
}

export async function restructureTranscript(sessionId: string, force = false, autoGenerate = true): Promise<RestructureTranscriptResult> {
  const res = await request(`/api/process/session/${sessionId}/restructure`, {
    method: 'POST',
    body: JSON.stringify({ force, auto_generate: autoGenerate }),
    timeoutMs: 120000,
  });
  return res as RestructureTranscriptResult;
}
