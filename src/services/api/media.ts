import { API_BASE, authHeaders } from './core';
import type { ContentBlock, PPTSlide, Slide } from './types';

export async function alignPPTWithText(sessionId: string, text: string): Promise<{ matched_page: number | null; similarity: number; slide?: PPTSlide }> {
  const res = await fetch(`${API_BASE}/api/process/ppt-align?session_id=${sessionId}&text=${encodeURIComponent(text)}`, {
    method: 'POST',
    headers: authHeaders(),
  });
  if (!res.ok) return { matched_page: null, similarity: 0 };
  return res.json();
}

export async function insertPPTIntoTranscript(sessionId: string, text?: string): Promise<{ blocks: ContentBlock[] }> {
  const res = await fetch(`${API_BASE}/api/process/ppt-insert?session_id=${sessionId}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body: JSON.stringify({ text: text ?? null }),
  });
  if (!res.ok) return { blocks: [] };
  return res.json();
}

export async function uploadPPT(file: File, sessionId: string): Promise<{ status: string; filename: string; total_pages?: number; slides?: Slide[] }> {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/api/process/ppt-upload?session_id=${sessionId}`, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });
  if (!res.ok) {
    const errorText = await res.text().catch(() => '');
    let message = errorText || `PPT/PDF 上传失败 (${res.status})`;
    try {
      const parsed = JSON.parse(errorText);
      if (typeof parsed.detail === 'string') message = parsed.detail;
    } catch {
      // Keep plain text response as the error message.
    }
    throw new Error(message);
  }
  return res.json();
}

export async function streamAudioChunk(
  audioBlob: Blob,
  sessionId: string,
  chunkIndex: number,
  onTranscribed: (text: string, timestamps: Array<{ text: string; start: number; end: number }>) => void,
): Promise<void> {
  const formData = new FormData();
  formData.append('file', audioBlob, `chunk_${chunkIndex}.wav`);
  const url = `${API_BASE}/api/process/audio-stream?session_id=${sessionId}&chunk_index=${chunkIndex}`;

  const res = await fetch(url, {
    method: 'POST',
    headers: authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    const errorText = await res.text();
    console.error(`[streamAudioChunk] Error response: ${res.status} ${errorText}`);
    throw new Error(`Audio stream failed: ${res.status}`);
  }

  const data = await res.json();
  if (data.corrected !== undefined && onTranscribed) {
    const text = data.corrected || data.original || '';
    const timestamps = data.timestamps || [];
    onTranscribed(text, timestamps);
  }
}

import type { AudioUploadCallbacks } from './types';

const CHUNK_THRESHOLD = 10 * 1024 * 1024; // 10MB
const CHUNK_SIZE = 5 * 1024 * 1024; // 5MB per chunk

function _parseSseStream(
  res: Response,
  callbacks: AudioUploadCallbacks,
  onComplete?: () => void,
): Promise<void> {
  const reader = res.body?.getReader();
  if (!reader) { callbacks.onError('No response body'); return Promise.resolve(); }

  const decoder = new TextDecoder();
  let buffer = '';

  return new Promise<void>((resolve) => {
    const pump = async () => {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6));
              switch (event.type) {
                case 'status':
                  callbacks.onStatus?.(event.message || '', event.segment ?? 0, event.total ?? 0);
                  break;
                case 'chunk':
                  callbacks.onChunk(
                    event.text,
                    event.segment ?? event.window ?? 0,
                    event.segment_total ?? event.total ?? 0,
                    {
                      chunkId: event.chunk_id,
                      rawText: event.raw_text,
                      isAiCorrected: event.is_ai_corrected,
                      correctionError: event.correction_error,
                      isFinal: event.is_final,
                    },
                  );
                  break;
                case 'correction':
                  callbacks.onCorrection?.(
                    event.text,
                    event.segment ?? 0,
                    event.segment_total ?? event.total ?? 0,
                    {
                      chunkId: event.chunk_id,
                      rawText: event.raw_text,
                      isAiCorrected: event.is_ai_corrected,
                      correctionError: event.correction_error,
                    },
                  );
                  break;
                case 'done':
                  callbacks.onDone(event.note || null);
                  break;
                case 'error':
                  callbacks.onError(event.detail || 'Unknown error');
                  break;
              }
            } catch (parseErr) {
              console.warn('[uploadAudio] SSE parse error:', parseErr);
              callbacks.onError('音频转写流解析失败');
            }
          }
        }
      }
      onComplete?.();
      resolve();
    };
    pump();
  });
}

export function uploadAudio(
  file: File,
  sessionId: string,
  callbacks: AudioUploadCallbacks,
): { abort: () => void } {
  const controller = new AbortController();

  const runUpload = async () => {
    if (file.size > CHUNK_THRESHOLD) {
      callbacks.onStatus?.('正在分片上传音频...', 0, Math.ceil(file.size / CHUNK_SIZE));
      const totalChunks = Math.ceil(file.size / CHUNK_SIZE);

      for (let i = 0; i < totalChunks; i++) {
        if (controller.signal.aborted) return;
        const start = i * CHUNK_SIZE;
        const end = Math.min(start + CHUNK_SIZE, file.size);
        const chunk = file.slice(start, end);

        const formData = new FormData();
        formData.append('file', chunk, `${file.name}.part${i}`);

        const res = await fetch(
          `${API_BASE}/api/process/audio-chunk?session_id=${sessionId}&chunk_index=${i}&total_chunks=${totalChunks}`,
          {
            method: 'POST',
            headers: authHeaders(),
            body: formData,
            signal: controller.signal,
          }
        );

        if (!res.ok) {
          const err = await res.json().catch(() => ({ detail: '分片上传失败' }));
          callbacks.onError(`Chunk ${i + 1}/${totalChunks} upload failed: ${err.detail || res.status}`);
          return;
        }
        callbacks.onStatus?.(`已上传 ${i + 1}/${totalChunks} 片`, i + 1, totalChunks);
      }

      if (controller.signal.aborted) return;

      callbacks.onStatus?.('分片上传完成，开始处理...', 0, 0);
      callbacks.onStart?.();
      const finishRes = await fetch(
        `${API_BASE}/api/process/audio-chunk-finish?session_id=${sessionId}&file_name=${encodeURIComponent(file.name)}&total_chunks=${totalChunks}`,
        {
          method: 'POST',
          headers: authHeaders(),
          signal: controller.signal,
        }
      );

      if (!finishRes.ok) {
        const err = await finishRes.json().catch(() => ({ detail: '处理失败' }));
        callbacks.onError(`Finish failed: ${err.detail || finishRes.status}`);
        return;
      }

      await _parseSseStream(finishRes, callbacks);
      return;
    }

    const formData = new FormData();
    formData.append('file', file);

    const res = await fetch(`${API_BASE}/api/process/audio-batch?session_id=${sessionId}`, {
      method: 'POST',
      headers: authHeaders(),
      body: formData,
      signal: controller.signal,
    });

    if (!res.ok) {
      const errorText = await res.text().catch(() => 'Unknown error');
      callbacks.onError(`Audio upload failed: ${res.status} ${errorText}`);
      return;
    }

    callbacks.onStart?.();
    await _parseSseStream(res, callbacks);
  };

  runUpload().catch((err) => {
    if (err.name === 'AbortError') return;
    callbacks.onError(err.message || 'Upload failed');
  });

  return { abort: () => controller.abort() };
}
