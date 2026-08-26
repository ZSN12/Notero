import { describe, expect, it } from 'vitest';
import { buildFreeNoteAiContext } from '../freeNoteAiContext';

describe('freeNoteAiContext', () => {
  it('builds context with title, status, text blocks and linked slide pages', () => {
    const context = buildFreeNoteAiContext({
      title: '公式推导',
      page: 3,
      reviewStatus: 'todo',
      strokes: [{ type: 'stroke', color: '#000', width: 4, points: [{ x: 0.1, y: 0.1 }] }],
      textBlocks: [{
        id: 't1',
        text: '课后重点',
        x: 0.1,
        y: 0.2,
        width: 0.4,
        color: '#111',
        fontSize: 18,
        createdAt: 'now',
        updatedAt: 'now',
      }],
      inserts: [
        { id: 's1', type: 'slide_snapshot', slideIndex: 1, dataUrl: 'data:', createdAt: 'now' },
        { id: 'img1', type: 'image', dataUrl: 'data:', createdAt: 'now' },
      ],
    });

    expect(context).toMatchObject({
      title: '公式推导',
      page: 3,
      reviewStatus: 'todo',
      slideIndexes: [1],
      slidePages: [2],
      textBlocks: ['课后重点'],
      hasHandwriting: true,
      hasSlideSnapshots: true,
      hasImages: true,
      imageCount: 1,
    });
  });

  it('handles an empty free note page without throwing', () => {
    expect(buildFreeNoteAiContext({
      title: '自由笔记 1',
      page: 1,
      reviewStatus: 'normal',
      inserts: [],
      textBlocks: [],
      strokes: [],
    })).toMatchObject({
      slideIndexes: [],
      textBlocks: [],
      hasHandwriting: false,
      hasSlideSnapshots: false,
      hasImages: false,
    });
  });
});
