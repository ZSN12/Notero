import { API_BASE } from './core';
import { getToken } from '../auth';
import type { BackendNotebook } from './types';

export async function importNotebook(pkg: unknown): Promise<BackendNotebook> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/notebooks/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify(pkg),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '导入失败' }));
    throw new Error(err.detail || '导入失败');
  }
  return res.json();
}

export async function exportNotebook(notebookId: string): Promise<unknown> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/notebooks/${notebookId}/export`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '导出失败' }));
    throw new Error(err.detail || '导出失败');
  }
  return res.json();
}
