import { API_BASE } from './core';
import { getToken } from '../auth';

export async function enableShare(
  sessionId: string,
  expiresInHours?: number,
  maxViews?: number,
): Promise<{ share_enabled: boolean; share_token: string; share_url: string; share_expires_at?: string; share_max_views?: number }> {
  const token = getToken();
  const params = new URLSearchParams();
  if (expiresInHours !== undefined) params.set('expires_in_hours', String(expiresInHours));
  if (maxViews !== undefined) params.set('max_views', String(maxViews));
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/share/enable?${params.toString()}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '开启分享失败' }));
    throw new Error(err.detail || '开启分享失败');
  }
  return res.json();
}

export async function disableShare(sessionId: string): Promise<{ share_enabled: boolean }> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/share/disable`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '关闭分享失败' }));
    throw new Error(err.detail || '关闭分享失败');
  }
  return res.json();
}

export async function getShareStatus(sessionId: string): Promise<{ share_enabled: boolean; share_token: string | null; share_url: string | null; share_expires_at?: string; share_max_views?: number; share_view_count?: number }> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}/share/status`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '获取分享状态失败' }));
    throw new Error(err.detail || '获取分享状态失败');
  }
  return res.json();
}

export function getShareMediaUrl(pathOrUrl: string, shareToken: string): string {
  if (pathOrUrl.startsWith('data:')) return pathOrUrl;
  const url = pathOrUrl.replace('/api/media/slides/', '/api/public/media/slides/');
  const fullUrl = new URL(url.startsWith('http') ? url : `${API_BASE}${url}`);
  fullUrl.searchParams.set('token', shareToken);
  return fullUrl.toString();
}
