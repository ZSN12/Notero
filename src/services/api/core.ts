import { getToken, clearToken } from '../auth';
import { API_BASE } from '@/config';
export { API_BASE };

export function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function getMediaUrl(pathOrUrl: string): string {
  return pathOrUrl.startsWith('http') ? pathOrUrl : `${API_BASE}${pathOrUrl}`;
}

export const iconMap: Record<string, string> = {
  'BookOpen': 'BookOpen',
  'Code': 'Code',
  'Brain': 'Brain',
  'Network': 'Network',
  'FileText': 'FileText',
};

export const colorMap: Record<number, string> = {
  0: 'from-blue-500 to-blue-600',
  1: 'from-violet-500 to-violet-600',
  2: 'from-emerald-500 to-emerald-600',
  3: 'from-orange-500 to-orange-600',
  4: 'from-pink-500 to-pink-600',
  5: 'from-cyan-500 to-cyan-600',
};

export function hashStringToInt(str: string): number {
  let hash = 0;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) - hash + str.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

interface ApiRequestOptions extends RequestInit {
  timeoutMs?: number;
}

export async function request<T = unknown>(url: string, options?: ApiRequestOptions): Promise<T> {
  const fullUrl = `${API_BASE}${url}`;
  const { timeoutMs = 20000, ...fetchOptions } = options || {};

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    const res = await fetch(fullUrl, {
      ...fetchOptions,
      signal: controller.signal,
      headers: {
        'Content-Type': 'application/json',
        ...authHeaders(),
        ...fetchOptions.headers,
      },
    });

    clearTimeout(timeoutId);

    if (res.status === 401) {
      clearToken();
      window.location.href = '/login';
      throw new Error('Unauthorized');
    }
    if (res.status === 204) return undefined as unknown as T;
    if (!res.ok) {
      const errorText = await res.text();
      let message = errorText || res.statusText;
      try {
        const parsed = JSON.parse(errorText);
        if (typeof parsed.detail === 'string') message = parsed.detail;
        else if (Array.isArray(parsed.detail)) message = parsed.detail.map((item: unknown) => (item as { msg?: string }).msg || JSON.stringify(item)).join('；');
      } catch (parseErr) {
        // Response body is not JSON; keep the raw status text as the error message.
        console.warn('[api] Failed to parse error response:', parseErr);
      }
      throw new Error(message || `请求失败 (${res.status})`);
    }

    return res.json();
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('请求超时，请稍后重试');
    }
    throw error;
  }
}

export function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hh = Math.floor(totalSeconds / 3600);
  const mm = Math.floor((totalSeconds % 3600) / 60);
  const ss = totalSeconds % 60;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
}
