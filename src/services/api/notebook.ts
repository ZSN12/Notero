import type { Notebook } from '@/types';
import { request } from './core';
import type { BackendNotebook } from './types';
import { mapBackendNotebook } from './mappers';

export async function fetchNotebooks(): Promise<Notebook[]> {
  const data = await request<BackendNotebook[]>('/api/notebooks/');
  return data.map(mapBackendNotebook);
}

export async function createNotebook(title: string): Promise<Notebook> {
  const data = await request<BackendNotebook>('/api/notebooks/', {
    method: 'POST',
    body: JSON.stringify({ title }),
  });
  return mapBackendNotebook(data);
}

export async function deleteNotebook(notebookId: string): Promise<void> {
  await request<void>(`/api/notebooks/${notebookId}`, { method: 'DELETE' });
}

export async function updateNotebook(notebookId: string, title: string): Promise<Notebook> {
  const data = await request<BackendNotebook>(`/api/notebooks/${notebookId}`, {
    method: 'PUT',
    body: JSON.stringify({ title }),
  });
  return mapBackendNotebook(data);
}

export async function fetchNotebookDetail(notebookId: string): Promise<BackendNotebook | null> {
  try {
    const data = await request<BackendNotebook>(`/api/notebooks/${notebookId}`);
    return data;
  } catch { return null; }
}
