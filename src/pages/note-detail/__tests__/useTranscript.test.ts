import { describe, it, expect } from 'vitest';
import { computeParagraphTimeRanges, type SentenceWithTime } from '../useTranscript';

describe('computeParagraphTimeRanges', () => {
  it('returns empty array when transcript text is empty', () => {
    const sentences: SentenceWithTime[] = [
      { text: '第一句。', startTime: 1, endTime: 2 },
    ];
    expect(computeParagraphTimeRanges('', sentences)).toEqual([]);
  });

  it('returns empty array when there are no sentences', () => {
    expect(computeParagraphTimeRanges('第一段。\n\n第二段。', [])).toEqual([]);
  });

  it('groups sentences into paragraphs by text containment', () => {
    const text = '第一段第一句。第一段第二句。\n\n第二段第一句。';
    const sentences: SentenceWithTime[] = [
      { text: '第一段第一句。', startTime: 1, endTime: 2.5 },
      { text: '第一段第二句。', startTime: 2.5, endTime: 4 },
      { text: '第二段第一句。', startTime: 5, endTime: 6 },
    ];

    expect(computeParagraphTimeRanges(text, sentences)).toEqual([
      { text: '第一段第一句。第一段第二句。', start_ms: 1000, end_ms: 4000 },
      { text: '第二段第一句。', start_ms: 5000, end_ms: 6000 },
    ]);
  });

  it('skips paragraphs that have no matching sentences', () => {
    const text = '有时间的段落。\n\n没有时间的段落。';
    const sentences: SentenceWithTime[] = [
      { text: '有时间的段落。', startTime: 1, endTime: 2 },
    ];

    expect(computeParagraphTimeRanges(text, sentences)).toEqual([
      { text: '有时间的段落。', start_ms: 1000, end_ms: 2000 },
    ]);
  });

  it('converts seconds to milliseconds and rounds', () => {
    const text = '只有一句。';
    const sentences: SentenceWithTime[] = [
      { text: '只有一句。', startTime: 1.234, endTime: 5.678 },
    ];

    expect(computeParagraphTimeRanges(text, sentences)).toEqual([
      { text: '只有一句。', start_ms: 1234, end_ms: 5678 },
    ]);
  });

  it('handles duplicate sentence text by assigning to the first matching paragraph', () => {
    const text = '重复。\n\n重复。';
    const sentences: SentenceWithTime[] = [
      { text: '重复。', startTime: 1, endTime: 2 },
      { text: '重复。', startTime: 3, endTime: 4 },
    ];

    const result = computeParagraphTimeRanges(text, sentences);
    // Both occurrences match the first paragraph, so the second paragraph has no timestamps.
    expect(result).toHaveLength(1);
    expect(result[0]).toEqual({ text: '重复。', start_ms: 1000, end_ms: 4000 });
  });
});
