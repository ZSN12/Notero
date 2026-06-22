import { request, getMediaUrl, API_BASE, authHeaders } from './core';
import type { BackendNote, TranscriptChunk, SessionAnnotations } from './types';

export type { SessionAnnotations, StrokeAnnotation } from './types';

export async function fetchNote(sessionId: string): Promise<BackendNote | null> {
  try {
    const data = await request<BackendNote>(`/api/notes/session/${sessionId}`);
    return data;
  } catch (err: any) {
    if (import.meta.env.DEV) {
      console.error(`[fetchNote] failed for session ${sessionId}:`, err?.message || err);
    }
    throw err;
  }
}

export async function updateNote(
  sessionId: string,
  content: string,
  layoutBlocks?: import('@/lib/noteLayout').NoteLayoutBlock[],
  annotations?: SessionAnnotations | null,
): Promise<BackendNote | null> {
  try {
    const payload: Record<string, unknown> = { content, layout_blocks: layoutBlocks };
    if (annotations !== undefined) {
      payload.annotations = annotations;
    }
    const data = await request<BackendNote>(`/api/notes/session/${sessionId}`, {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    return data;
  } catch (err: any) {
    if (import.meta.env.DEV) {
      console.error(`[updateNote] failed for session ${sessionId}:`, err?.message || err);
    }
    throw err;
  }
}

export async function finishRecording(sessionId: string): Promise<{ status: string; audio_path: string | null; note?: any }> {
  try {
    // Audio concatenation can take a few seconds for long recordings. Real-time
    // recording stop no longer triggers AI finalization automatically; the user
    // must click "AI 整理" to run the unified restructure.
    const data = await request<{ status: string; audio_path: string | null; note?: any }>(
      `/api/process/audio-finish?session_id=${sessionId}`,
      { method: 'POST', timeoutMs: 60000 }
    );
    return data;
  } catch {
    return { status: 'error', audio_path: null };
  }
}

export function getAudioUrl(sessionId: string): string {
  return getMediaUrl(`/api/media/audio/${sessionId}.wav`);
}

export async function deleteAudio(sessionId: string): Promise<boolean> {
  try {
    await request<void>(`/api/process/audio?session_id=${sessionId}`, { method: 'DELETE' });
    return true;
  } catch {
    return false;
  }
}

export async function updateTranscript(sessionId: string, transcript: TranscriptChunk[]): Promise<void> {
  try {
    await request<void>(`/api/process/transcript?session_id=${sessionId}`, {
      method: 'PUT',
      body: JSON.stringify({ content: JSON.stringify(transcript) }),
    });
  } catch {
    // ignore
  }
}

export interface FinalizeTranscriptResult {
  note: BackendNote;
  agents: { workflow_id?: string; session_id: string; agents?: Array<{ role: string; task_id: string | null; status: string; progress: number; error: string | null }>; reused?: boolean } | null;
}

export async function finalizeTranscript(
  sessionId: string,
  autoGenerate = true,
  force = false,
  retryFailedOnly = false,
): Promise<FinalizeTranscriptResult> {
  const res = await fetch(`${API_BASE}/api/process/transcript-finalize?session_id=${sessionId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify({ auto_generate: autoGenerate, force, retry_failed_only: retryFailedOnly }),
  });
  if (!res.ok) {
    const errText = await res.text().catch(() => 'Unknown error');
    throw new Error(`Finalization failed: ${res.status} ${errText}`);
  }
  return res.json();
}
