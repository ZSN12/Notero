import { request } from './core';
import type { VectorIndexStatus, VectorSearchResult } from './types';

export async function rebuildSessionVectorIndex(sessionId: string): Promise<{ session_id: string; chunk_count: number; status: string }> {
  return request(`/api/vector/session/${sessionId}/rebuild`, { method: 'POST' });
}

export async function rebuildNotebookVectorIndex(notebookId: string): Promise<{ notebook_id: string; chunk_count: number; status: string }> {
  return request(`/api/vector/notebook/${notebookId}/rebuild`, { method: 'POST' });
}

export async function getSessionVectorStatus(sessionId: string): Promise<VectorIndexStatus> {
  return request(`/api/vector/session/${sessionId}/status`);
}

export async function searchVectors(query: string, sessionId?: string, notebookId?: string, limit: number = 20): Promise<{ results: VectorSearchResult[]; total: number }> {
  return request('/api/vector/search', {
    method: 'POST',
    body: JSON.stringify({ query, session_id: sessionId, notebook_id: notebookId, limit }),
  });
}
