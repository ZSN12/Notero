import { describe, it, expect } from 'vitest';
import { buildCorrectionStatus } from '../useRestructure';

describe('buildCorrectionStatus', () => {
  it('returns corrected when is_ai_corrected is true', () => {
    const status = buildCorrectionStatus({
      is_ai_corrected: true,
      correction_stage: 'final',
    });
    expect(status.type).toBe('corrected');
  });

  it('returns partial with counts when some chunks failed', () => {
    const status = buildCorrectionStatus({
      is_ai_corrected: false,
      correction_error_code: 'timeout',
      correction_retryable: true,
      ai_chunks_total: 4,
      ai_chunks_succeeded: 3,
      ai_chunks_failed: 1,
      correction_stage: 'final',
    });
    expect(status.type).toBe('partial');
    expect(status.message).toContain('共 4 段');
    expect(status.message).toContain('成功 3 段');
    expect(status.message).toContain('失败 1 段');
    expect(status.retryable).toBe(true);
    expect(status.code).toBe('timeout');
  });

  it('maps error codes to user messages', () => {
    const status = buildCorrectionStatus({
      is_ai_corrected: false,
      correction_error_code: 'rate_limit',
      correction_retryable: true,
      correction_stage: 'final',
    });
    expect(status.type).toBe('error');
    expect(status.message).toBe('AI 服务限流，请稍后重试');
  });

  it('falls back to local for unclassified errors', () => {
    const status = buildCorrectionStatus({
      is_ai_corrected: false,
      correction_error: '已使用本地整理稿',
      correction_stage: 'final',
    });
    expect(status.type).toBe('local');
    expect(status.message).toBe('已使用本地整理稿');
  });
});
