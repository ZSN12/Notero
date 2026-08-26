import { describe, expect, it } from 'vitest';
import { getFreeNoteSourcePage } from '../ragSourceNavigation';
import type { RAGSource } from '@/services/api/types';

function makeSource(source: Partial<RAGSource>): RAGSource {
  return {
    chunk_id: 'c1',
    notebook_id: 'nb1',
    notebook_title: 'Notebook',
    session_id: 's1',
    session_title: 'Session',
    source_type: 'free_note',
    snippet: '',
    score: 1,
    ...source,
  };
}

describe('ragSourceNavigation', () => {
  it('reads free note page from source.page first', () => {
    expect(getFreeNoteSourcePage(makeSource({ page: '3', metadata: { pageIndex: 2 } }))).toBe(3);
  });

  it('falls back to metadata pageIndex for free note sources', () => {
    expect(getFreeNoteSourcePage(makeSource({ metadata: { pageIndex: 2 } }))).toBe(2);
  });

  it('ignores non-free-note and invalid pages', () => {
    expect(getFreeNoteSourcePage(makeSource({ source_type: 'ppt', page: 2 }))).toBeNull();
    expect(getFreeNoteSourcePage(makeSource({ page: 0 }))).toBeNull();
  });
});
