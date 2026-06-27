import { API_BASE } from '@/config';

const TOKEN_KEY = "notero_token";

export interface UserProfile {
  id: string;
  email: string;
  username?: string | null;
  avatar_url?: string | null;
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getToken() !== null;
}

async function authFetch(path: string, body: object): Promise<Response> {
  const controller = new AbortController();
  const url = `${API_BASE}${path}`;
  const startedAt = performance.now();
  const timeout = setTimeout(() => controller.abort(), 60000);

  try {
    if (import.meta.env.DEV) console.info(`[auth] POST ${url}`);
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (import.meta.env.DEV) {
      console.info(`[auth] ${res.status} ${url} ${Math.round(performance.now() - startedAt)}ms`);
    }
    return res;
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      if (import.meta.env.DEV) {
        console.warn(`[auth] timeout ${url} ${Math.round(performance.now() - startedAt)}ms`);
      }
      throw new Error("请求超时，请检查后端是否在 8003 端口运行");
    }
    if (import.meta.env.DEV) console.warn(`[auth] failed ${url}`, err);
    throw new Error(`无法连接到服务器 (${API_BASE})，请确认后端已启动`);
  } finally {
    clearTimeout(timeout);
  }
}

function formatErrorDetail(detail: unknown): string {
  if (typeof detail === "string") {
    return detail;
  }
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const msg = (detail as { msg?: string }).msg;
    if (msg) return msg;
    return JSON.stringify(detail);
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (item && typeof item === "object") {
          const msg = (item as { msg?: string }).msg;
          return typeof msg === "string" ? msg : JSON.stringify(item);
        }
        return String(item);
      })
      .filter(Boolean)
      .map((msg) => msg.replace(/^Value error,\s*/i, ""));
    return messages.join("；") || "请求失败";
  }
  return "请求失败";
}

export async function login(email: string, password: string): Promise<string> {
  const res = await authFetch("/api/auth/login", { email, password });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "登录失败" }));
    throw new Error(formatErrorDetail(err.detail) || "登录失败");
  }
  const data = await res.json();
  setToken(data.access_token);
  return data.access_token;
}

export async function register(username: string, email: string, password: string): Promise<void> {
  const res = await authFetch("/api/auth/register", { username, email, password });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "注册失败" }));
    throw new Error(formatErrorDetail(err.detail) || "注册失败");
  }
}

export function logout(): void {
  clearToken();
  window.location.href = "/login";
}

export async function resetPassword(email: string, newPassword: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/auth/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, new_password: newPassword }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "密码重置失败" }));
    throw new Error(err.detail || "密码重置失败");
  }
}

export async function getProfile(): Promise<UserProfile> {
  const token = getToken();
  if (!token) throw new Error("Not authenticated");
  const res = await fetch(`${API_BASE}/api/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch profile");
  return res.json();
}

export async function updateProfile(username: string): Promise<UserProfile> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/auth/profile`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ username }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "更新失败" }));
    throw new Error(err.detail || "更新失败");
  }
  return res.json();
}

export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/api/auth/change-password`, {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "密码修改失败" }));
    throw new Error(err.detail || "密码修改失败");
  }
}

export async function uploadAvatar(file: File): Promise<string> {
  const token = getToken();
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch(`${API_BASE}/api/auth/avatar`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "头像上传失败" }));
    throw new Error(err.detail || "头像上传失败");
  }
  const data = await res.json();
  return data.avatar_url;
}

export function getAvatarUrl(userId: string): string {
  return `${API_BASE}/api/auth/avatar/${userId}`;
}
