import { request } from './core';
import type { MindMapStatus } from './types';

export async function getSessionMindMap(sessionId: string): Promise<MindMapStatus> {
  return request(`/api/mindmap/session/${sessionId}`, { timeoutMs: 15000 });
}

export async function generateSessionMindMap(sessionId: string, force = false): Promise<MindMapStatus> {
  const query = force ? '?force=true' : '';
  return request(`/api/mindmap/session/${sessionId}/generate${query}`, { method: 'POST', timeoutMs: 15000 });
}

export async function deleteSessionMindMap(sessionId: string): Promise<{ session_id: string; status: string }> {
  return request(`/api/mindmap/session/${sessionId}`, { method: 'DELETE' });
}

export async function saveMindMapPositions(sessionId: string, positions: Record<string, { x: number; y: number }>): Promise<void> {
  await request(`/api/mindmap/session/${sessionId}/positions`, {
    method: 'PATCH',
    body: JSON.stringify({ positions }),
    timeoutMs: 10000,
  });
}
