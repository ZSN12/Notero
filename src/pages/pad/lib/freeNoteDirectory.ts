import type { FreeNoteInsert, FreeNoteReviewStatus } from '@/services/api/types';
import type { FreeNotePageSummary } from '@/pages/pad/hooks/usePadAnnotations';

export type FreeNoteQueueFilter = 'all' | 'important' | 'todo';

export function getInsertSlideNumbers(inserts: FreeNoteInsert[] = []): number[] {
  return Array.from(new Set(
    inserts
      .filter((insert) => insert.type === 'slide_snapshot')
      .map((insert) => (insert.slideIndex ?? -1) + 1)
      .filter((value) => Number.isFinite(value) && value > 0),
  )).sort((a, b) => a - b);
}

export function filterFreeNoteSummaries(
  summaries: FreeNotePageSummary[],
  query: string,
): FreeNotePageSummary[] {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) return summaries;
  return summaries.filter((item) => {
    const defaultTitle = `自由笔记 ${item.page}`;
    const slideNumbers = getInsertSlideNumbers(item.inserts);
    const searchable = [
      item.title,
      defaultTitle,
      ...slideNumbers.map((pageNumber) => `ppt ${pageNumber}`),
      ...slideNumbers.map(String),
    ].join(' ').toLowerCase();
    return searchable.includes(normalizedQuery);
  });
}

export function getRelatedFreeNoteSummaries(
  summaries: FreeNotePageSummary[],
  slideIndex: number,
): FreeNotePageSummary[] {
  return summaries.filter((item) =>
    item.inserts.some((insert) => insert.type === 'slide_snapshot' && insert.slideIndex === slideIndex) ||
    item.metadata?.slide_indexes?.includes(slideIndex),
  );
}

export function getReviewQueueSummaries(
  summaries: FreeNotePageSummary[],
  filter: FreeNoteQueueFilter = 'all',
): FreeNotePageSummary[] {
  return summaries.filter((item) =>
    filter === 'all'
      ? item.reviewStatus === 'important' || item.reviewStatus === 'todo'
      : item.reviewStatus === filter,
  );
}

export function getFreeNoteReviewStats(summaries: FreeNotePageSummary[]) {
  const initial: Record<FreeNoteReviewStatus, number> & { aiPages: number } = {
    normal: 0,
    important: 0,
    todo: 0,
    reviewed: 0,
    aiPages: 0,
  };
  return summaries.reduce((acc, item) => {
    acc[item.reviewStatus] += 1;
    if (item.aiBlocks.length > 0) acc.aiPages += 1;
    return acc;
  }, initial);
}
