import { describe, expect, it } from 'vitest';
import { filterFreeNoteSummaries, getFreeNoteReviewStats, getRelatedFreeNoteSummaries, getReviewQueueSummaries } from '../freeNoteDirectory';
import type { FreeNotePageSummary } from '@/pages/pad/hooks/usePadAnnotations';

const baseSummary: FreeNotePageSummary = {
  page: 1,
  title: '自由笔记 1',
  background: 'grid',
  strokes: [],
  inserts: [],
  textBlocks: [],
  aiBlocks: [],
  reviewStatus: 'normal',
  isBlank: true,
};

function makeSummary(summary: Partial<FreeNotePageSummary>): FreeNotePageSummary {
  return { ...baseSummary, ...summary };
}

describe('freeNoteDirectory', () => {
  it('filters free note pages by title and default page name', () => {
    const summaries = [
      makeSummary({ page: 1, title: '公式推导' }),
      makeSummary({ page: 2, title: '自由笔记 2' }),
    ];

    expect(filterFreeNoteSummaries(summaries, '公式')).toEqual([summaries[0]]);
    expect(filterFreeNoteSummaries(summaries, '自由笔记 2')).toEqual([summaries[1]]);
  });

  it('keeps review status available for directory filtering', () => {
    const summaries = [
      makeSummary({ page: 1, title: '重点页', reviewStatus: 'important' }),
      makeSummary({ page: 2, title: '待处理', reviewStatus: 'todo' }),
    ];

    expect(filterFreeNoteSummaries(summaries, '').filter((item) => item.reviewStatus === 'todo')).toEqual([summaries[1]]);
  });

  it('filters free note pages by user-visible PPT page number', () => {
    const summaries = [
      makeSummary({
        page: 1,
        title: '截图页',
        inserts: [{ id: 'i1', type: 'slide_snapshot', slideIndex: 2, dataUrl: 'data:', createdAt: 'now' }],
      }),
    ];

    expect(filterFreeNoteSummaries(summaries, '3')).toEqual([summaries[0]]);
    expect(filterFreeNoteSummaries(summaries, 'PPT 3')).toEqual([summaries[0]]);
  });

  it('finds and updates related free note pages from inserts and metadata', () => {
    const withInsert = makeSummary({
      page: 1,
      inserts: [{ id: 'i1', type: 'slide_snapshot', slideIndex: 1, dataUrl: 'data:', createdAt: 'now' }],
      isBlank: false,
    });
    const withMetadata = makeSummary({ page: 4, metadata: { page: 4, background: 'grid', has_strokes: false, has_slide_snapshot: true, slide_indexes: [1] } });
    const unrelated = makeSummary({ page: 5 });

    expect(getRelatedFreeNoteSummaries([withInsert, withMetadata, unrelated], 1).map((item) => item.page)).toEqual([1, 4]);
    expect(getRelatedFreeNoteSummaries([{ ...withInsert, inserts: [] }, withMetadata, unrelated], 1).map((item) => item.page)).toEqual([4]);
  });

  it('does not treat normal image inserts as related PPT notes', () => {
    const imageOnly = makeSummary({
      page: 1,
      inserts: [{ id: 'img', type: 'image', dataUrl: 'data:', createdAt: 'now' }],
    });

    expect(getRelatedFreeNoteSummaries([imageOnly], 1)).toEqual([]);
    expect(filterFreeNoteSummaries([imageOnly], 'PPT 2')).toEqual([]);
  });

  it('builds a review queue from important and todo pages', () => {
    const important = makeSummary({ page: 1, reviewStatus: 'important' });
    const todo = makeSummary({ page: 3, reviewStatus: 'todo' });
    const reviewed = makeSummary({ page: 4, reviewStatus: 'reviewed' });

    expect(getReviewQueueSummaries([important, todo, reviewed]).map((item) => item.page)).toEqual([1, 3]);
    expect(getReviewQueueSummaries([important, todo, reviewed], 'todo')).toEqual([todo]);
  });

  it('summarizes free note review progress and AI pages', () => {
    const summaries = [
      makeSummary({ page: 1, reviewStatus: 'normal' }),
      makeSummary({ page: 2, reviewStatus: 'important', aiBlocks: [{ id: 'a1', type: 'summary', title: '总结', content: '内容', sourceContext: {}, createdAt: 'now', updatedAt: 'now' }] }),
      makeSummary({ page: 3, reviewStatus: 'todo' }),
      makeSummary({ page: 4, reviewStatus: 'reviewed' }),
    ];

    expect(getFreeNoteReviewStats(summaries)).toEqual({
      normal: 1,
      important: 1,
      todo: 1,
      reviewed: 1,
      aiPages: 1,
    });
  });
});
