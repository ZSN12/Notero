import { useState } from 'react';
import { finalizeTranscript } from '@/services/api';
import { transcriptTextFromRawTranscript } from '@/lib/noteLayout';

interface TranscriptEntry {
  correction_stage?: string;
  is_ai_corrected?: boolean;
  correction_error?: string;
  correction_error_code?: string;
  correction_error_type?: string;
  correction_request_id?: string;
  correction_retryable?: boolean;
  ai_chunks_total?: number;
  ai_chunks_succeeded?: number;
  ai_chunks_failed?: number;
}

export type CorrectionStatusType = 'idle' | 'processing' | 'corrected' | 'partial' | 'local' | 'error';

export interface CorrectionStatus {
  type: CorrectionStatusType;
  message?: string;
  code?: string;
  errorType?: string;
  requestId?: string;
  retryable?: boolean;
  chunksTotal?: number;
  chunksSucceeded?: number;
  chunksFailed?: number;
}

const CODE_TO_MESSAGE: Record<string, string> = {
  timeout: 'AI 整理超时',
  rate_limit: 'AI 服务限流，请稍后重试',
  authentication: 'AI 服务认证失败，请检查 API Key',
  network: '网络连接失败',
  empty_response: 'AI 返回内容为空',
  truncated_response: 'AI 返回内容不完整',
  invalid_response: 'AI 返回格式异常',
  server_error: 'AI 服务内部错误，请稍后重试',
  content_filter: 'AI 服务拒绝处理该内容，请检查文本是否合规',
  unknown: 'AI 整理发生内部异常',
};

function buildUnknownMessage(entry: TranscriptEntry): string {
  const details: string[] = [];
  if (entry.correction_error_type) {
    details.push(`异常类型：${entry.correction_error_type}`);
  }
  if (entry.correction_request_id) {
    details.push(`请求 ID：${entry.correction_request_id}`);
  }
  const suffix = details.length > 0 ? `（${details.join('，')}）` : '';
  return `${CODE_TO_MESSAGE.unknown}${suffix}，请查看后端日志或重新尝试`;
}

export function buildCorrectionStatus(entry: TranscriptEntry | undefined): CorrectionStatus {
  if (!entry) return { type: 'local' };

  const total = entry.ai_chunks_total ?? 0;
  const succeeded = entry.ai_chunks_succeeded ?? 0;
  const failed = entry.ai_chunks_failed ?? 0;
  const code = entry.correction_error_code;
  const retryable = entry.correction_retryable ?? false;

  if (entry.is_ai_corrected) {
    return { type: 'corrected' };
  }

  if (succeeded > 0 && failed > 0) {
    const base = (code && CODE_TO_MESSAGE[code]) || 'AI 整理部分失败';
    return {
      type: 'partial',
      message: `${base}：长转写共 ${total} 段，成功 ${succeeded} 段、失败 ${failed} 段`,
      code,
      errorType: entry.correction_error_type,
      requestId: entry.correction_request_id,
      retryable,
      chunksTotal: total,
      chunksSucceeded: succeeded,
      chunksFailed: failed,
    };
  }

  if (code) {
    const message =
      code === 'unknown'
        ? buildUnknownMessage(entry)
        : CODE_TO_MESSAGE[code] || entry.correction_error || 'AI 整理失败';
    return {
      type: 'error',
      message,
      code,
      errorType: entry.correction_error_type,
      requestId: entry.correction_request_id,
      retryable,
      chunksTotal: total,
      chunksSucceeded: succeeded,
      chunksFailed: failed,
    };
  }

  if (entry.correction_error) {
    return { type: 'local', message: entry.correction_error };
  }

  return { type: 'local' };
}

export function getErrorLabel(status: CorrectionStatus): string {
  switch (status.code) {
    case 'timeout':
      return 'AI 整理超时';
    case 'rate_limit':
      return 'AI 服务限流';
    case 'authentication':
      return 'AI 认证失败';
    case 'network':
      return '网络连接失败';
    case 'empty_response':
      return 'AI 返回为空';
    case 'truncated_response':
      return 'AI 返回不完整';
    case 'invalid_response':
      return 'AI 返回格式异常';
    case 'server_error':
      return 'AI 服务内部错误';
    case 'content_filter':
      return 'AI 内容被拒绝';
    case 'unknown':
      return status.errorType ? `AI 整理内部异常（${status.errorType}）` : 'AI 整理内部异常';
    default:
      return 'AI 整理失败';
  }
}

export function useRestructure() {
  const [isRestructuring, setIsRestructuring] = useState(false);

  const handleRestructure = async (
    sessionId: string | undefined,
    onReceiveAiText: (text: string, options?: { force?: boolean }) => void,
    onCorrectionStatus: (status: CorrectionStatus) => void,
    options: { autoGenerate?: boolean; retryFailedOnly?: boolean } = {},
  ): Promise<boolean> => {
    if (!sessionId) return false;
    setIsRestructuring(true);
    onCorrectionStatus({ type: 'processing', message: '正在 AI 整理...' });
    try {
      const result = await finalizeTranscript(
        sessionId,
        options.autoGenerate ?? true,
        false,
        options.retryFailedOnly ?? false,
      );
      const note = result?.note;
      if (note?.transcript && note.transcript.length > 0) {
        const dbText = transcriptTextFromRawTranscript(note.transcript);
        if (dbText) {
          onReceiveAiText(dbText, { force: true });
        }
        // Determine correction status from the latest authoritative entry only.
        let latest: TranscriptEntry | undefined;
        for (const entry of note.transcript as TranscriptEntry[]) {
          if (entry && (entry.correction_stage === 'final' || entry.correction_stage === 'user_edited')) {
            latest = entry;
          }
        }
        onCorrectionStatus(buildCorrectionStatus(latest));
      }
      return true;
    } catch (err: unknown) {
      console.error('Restructure failed:', err);
      onCorrectionStatus({ type: 'error', message: err instanceof Error ? err.message : '整理失败' });
      return false;
    } finally {
      setIsRestructuring(false);
    }
  };

  return {
    state: { isRestructuring },
    actions: { handleRestructure },
  };
}
