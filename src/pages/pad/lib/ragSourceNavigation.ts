import type { RAGSource } from '@/services/api/types';

export function getFreeNoteSourcePage(source: RAGSource): number | null {
  if (source.source_type !== 'free_note') return null;
  const metadataPage = source.metadata?.pageIndex ?? source.metadata?.page_index ?? source.metadata?.page;
  const page = source.page == null ? Number(metadataPage) : Number(source.page);
  return Number.isFinite(page) && page > 0 ? page : null;
}
