import type { Session } from '@/types';
import { request } from './core';
import type { BackendSession } from './types';
import { mapBackendSession } from './mappers';

export async function fetchSessions(notebookId: string): Promise<Session[]> {
  const data = await request<BackendSession[]>(`/api/sessions/?notebook_id=${notebookId}`, { timeoutMs: 20000 });
  return data.map(mapBackendSession);
}

export async function fetchSessionDetail(notebookId: string): Promise<BackendSession[]> {
  try {
    const data = await request<BackendSession[]>(`/api/sessions/?notebook_id=${notebookId}`, { timeoutMs: 20000 });
    return data;
  } catch { return []; }
}

export async function fetchSessionById(sessionId: string): Promise<Session | null> {
  try {
    const data = await request<BackendSession>(`/api/sessions/${sessionId}`);
    return mapBackendSession(data);
  } catch { return null; }
}

export async function createSession(notebookId: string, title: string): Promise<Session> {
  const data = await request<BackendSession>(`/api/sessions/?notebook_id=${notebookId}`, {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
  return mapBackendSession(data);
}

export async function deleteSession(sessionId: string): Promise<void> {
  await request<void>(`/api/sessions/${sessionId}`, { method: 'DELETE' });
}

export async function updateSession(sessionId: string, title: string): Promise<Session> {
  const data = await request<BackendSession>(`/api/sessions/${sessionId}`, {
    method: 'PUT',
    body: JSON.stringify({ title }),
  });
  return mapBackendSession(data);
}

export async function updateSessionDuration(sessionId: string, durationMs: number): Promise<void> {
  const duration = formatDuration(durationMs);
  await request<void>(`/api/sessions/${sessionId}`, {
    method: 'PUT',
    body: JSON.stringify({ duration }),
  });
}

// Re-import to avoid circular deps if we later split further
function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hh = Math.floor(totalSeconds / 3600);
  const mm = Math.floor((totalSeconds % 3600) / 60);
  const ss = totalSeconds % 60;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
}
