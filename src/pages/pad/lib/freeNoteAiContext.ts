import type { FreeNoteInsert, FreeNoteReviewStatus, FreeNoteTextBlock, StrokeAnnotation } from '@/services/api/types';

export interface FreeNoteAiContextInput {
  title: string;
  page: number;
  reviewStatus: FreeNoteReviewStatus;
  inserts: FreeNoteInsert[];
  textBlocks: FreeNoteTextBlock[];
  strokes: StrokeAnnotation[];
}

export function buildFreeNoteAiContext(input: FreeNoteAiContextInput) {
  const slideIndexes = Array.from(new Set(
    input.inserts
      .filter((insert) => insert.type === 'slide_snapshot' && typeof insert.slideIndex === 'number')
      .map((insert) => insert.slideIndex!),
  )).sort((a, b) => a - b);
  return {
    title: input.title,
    page: input.page,
    reviewStatus: input.reviewStatus,
    slideIndexes,
    slidePages: slideIndexes.map((index) => index + 1),
    textBlocks: input.textBlocks.map((block) => block.text).filter((text) => text.trim()),
    hasHandwriting: input.strokes.length > 0,
    hasSlideSnapshots: input.inserts.some((insert) => insert.type === 'slide_snapshot'),
    hasImages: input.inserts.some((insert) => insert.type === 'image'),
    imageCount: input.inserts.filter((insert) => insert.type === 'image').length,
  };
}
