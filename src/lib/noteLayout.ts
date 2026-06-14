import type { ContentBlock, Slide } from '@/services/api';

export type NoteLayoutBlockType = 'transcript' | 'ppt' | 'note';

export interface NoteLayoutBlock {
  id: string;
  type: NoteLayoutBlockType;
  content?: string;
  src?: string;
  page?: number;
  title?: string;
}

export interface StudentNoteLike {
  type: string;
  content: string;
}

function blockId(type: NoteLayoutBlockType, index: number): string {
  return `${type}-${index + 1}`;
}

export function normalizeHtmlText(value?: string | null): string {
  const trimmed = (value || '').trim();
  return trimmed === '<br>' || trimmed === '<br />' || /^[-\s]+$/.test(trimmed) ? '' : trimmed;
}

export function transcriptTextFromRawTranscript(transcript?: unknown[] | null): string {
  if (!Array.isArray(transcript) || transcript.length === 0) return '';

  // Use the latest authoritative entry as the single source of truth so that
  // user edits and deletions are not mixed with older final/local entries.
  let latest: Record<string, unknown> | undefined;
  for (const entry of transcript) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue;
    const stage = (entry as Record<string, unknown>).correction_stage;
    if (stage === 'final' || stage === 'user_edited') {
      latest = entry as Record<string, unknown>;
    }
  }
  if (latest) {
    const text =
      latest.display_text ??
      latest.corrected_text ??
      latest.text ??
      latest.raw_text ??
      '';
    return String(text).trim();
  }

  // Fallback: join non-superseded entries in chunk order.
  return [...transcript]
    .filter((e) => (e as Record<string, unknown>)?.correction_stage !== 'superseded')
    .sort((a, b) => Number((a as Record<string, unknown>)?.chunk_index || 0) - Number((b as Record<string, unknown>)?.chunk_index || 0))
    .map((chunk) => (chunk as Record<string, unknown>)?.text || '')
    .join(' ')
    .trim();
}

export function transcriptTextFromContent(content?: string | null): string {
  if (!content) return '';
  const match = content.match(/^## 语音转文字\n\n([\s\S]*?)(?:\n\n---\n\n[\s\S]*)?$/);
  return normalizeHtmlText(match?.[1] || '');
}

export function notesFromContent(content?: string | null, hasTranscript = false): StudentNoteLike[] {
  if (!content) return [];
  const match = content.match(/^## 语音转文字\n\n([\s\S]*?)\n\n---\n\n([\s\S]*)$/);
  if (match?.[2]?.trim()) return [{ type: 'text', content: normalizeHtmlText(match[2]) }];
  if (!hasTranscript && !content.startsWith('## 语音转文字\n\n') && content.trim()) {
    return [{ type: 'text', content: normalizeHtmlText(content) }];
  }
  return [];
}

export function contentBlocksFromLayout(layoutBlocks?: NoteLayoutBlock[] | null): ContentBlock[] {
  if (!Array.isArray(layoutBlocks)) return [];
  return layoutBlocks
    .filter((block) => block.type === 'transcript' || block.type === 'ppt')
    .map((block) => {
      if (block.type === 'ppt') {
        return {
          type: 'image',
          src: block.src,
          page: block.page,
          title: block.title,
        } satisfies ContentBlock;
      }
      return {
        type: 'text',
        content: block.content || '',
      } satisfies ContentBlock;
    });
}

export function notesFromLayout(layoutBlocks?: NoteLayoutBlock[] | null): StudentNoteLike[] {
  if (!Array.isArray(layoutBlocks)) return [];
  return layoutBlocks
    .filter((block) => block.type === 'note' && normalizeHtmlText(block.content))
    .map((block) => ({ type: 'text', content: block.content || '' }));
}

export function layoutFromNoteParts(
  transcriptText: string,
  contentBlocks: ContentBlock[],
  notes: StudentNoteLike[],
): NoteLayoutBlock[] {
  const layout: NoteLayoutBlock[] = [];
  const usableBlocks = contentBlocks.filter((block) => {
    if (block.type === 'image') return !!block.src || !!block.page;
    if (block.type === 'text') return !!normalizeHtmlText(block.content);
    return false;
  });

  if (usableBlocks.length > 0) {
    usableBlocks.forEach((block) => {
      if (block.type === 'image') {
        layout.push({
          id: blockId('ppt', layout.length),
          type: 'ppt',
          src: block.src,
          page: block.page,
          title: block.title,
        });
      } else if (block.type === 'text') {
        layout.push({
          id: blockId('transcript', layout.length),
          type: 'transcript',
          content: normalizeHtmlText(block.content),
        });
      }
    });
  } else {
    const paragraphs = normalizeHtmlText(transcriptText)
      .split(/\n{2,}/)
      .map((part) => normalizeHtmlText(part))
      .filter(Boolean);
    paragraphs.forEach((paragraph) => {
      layout.push({
        id: blockId('transcript', layout.length),
        type: 'transcript',
        content: paragraph,
      });
    });
  }

  notes
    .map((note) => normalizeHtmlText(note.content))
    .filter(Boolean)
    .forEach((content) => {
      layout.push({
        id: blockId('note', layout.length),
        type: 'note',
        content,
      });
    });

  return layout;
}

export function fallbackLayoutFromNote(note: {
  content?: string | null;
  transcript?: unknown[] | null;
  layout_blocks?: NoteLayoutBlock[] | null;
}): NoteLayoutBlock[] {
  if (Array.isArray(note.layout_blocks) && note.layout_blocks.length > 0) return note.layout_blocks;
  const transcriptText = transcriptTextFromContent(note.content) || transcriptTextFromRawTranscript(note.transcript);
  return layoutFromNoteParts(transcriptText, [], notesFromContent(note.content, !!transcriptText));
}

export function slideImageSrc(slide?: Slide): string | undefined {
  return slide?.image_path || slide?.image_base64;
}
