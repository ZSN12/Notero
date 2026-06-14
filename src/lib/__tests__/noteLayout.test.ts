import { describe, it, expect } from 'vitest'
import {
  normalizeHtmlText,
  transcriptTextFromRawTranscript,
  transcriptTextFromContent,
  notesFromContent,
  contentBlocksFromLayout,
  notesFromLayout,
  layoutFromNoteParts,
  fallbackLayoutFromNote,
  slideImageSrc,
} from '@/lib/noteLayout'
import type { NoteLayoutBlock, StudentNoteLike } from '@/lib/noteLayout'

describe('normalizeHtmlText', () => {
  it('returns empty for <br>', () => {
    expect(normalizeHtmlText('<br>')).toBe('')
    expect(normalizeHtmlText('<br />')).toBe('')
  })

  it('returns empty for whitespace-only', () => {
    expect(normalizeHtmlText('   ')).toBe('')
    expect(normalizeHtmlText('---')).toBe('')
  })

  it('returns trimmed text otherwise', () => {
    expect(normalizeHtmlText('  hello  ')).toBe('hello')
    expect(normalizeHtmlText('world')).toBe('world')
  })

  it('handles null/undefined', () => {
    expect(normalizeHtmlText(null)).toBe('')
    expect(normalizeHtmlText(undefined)).toBe('')
  })
})

describe('transcriptTextFromRawTranscript', () => {
  it('returns empty for empty/null input', () => {
    expect(transcriptTextFromRawTranscript(null)).toBe('')
    expect(transcriptTextFromRawTranscript([])).toBe('')
  })

  it('sorts by chunk_index and joins text', () => {
    const transcript = [
      { chunk_index: 2, text: 'world' },
      { chunk_index: 0, text: 'hello' },
      { chunk_index: 1, text: ' ' },
    ]
    expect(transcriptTextFromRawTranscript(transcript)).toBe('hello   world')
  })

  it('skips missing text fields', () => {
    const transcript = [
      { chunk_index: 0, text: 'hello' },
      { chunk_index: 1 },
      { chunk_index: 2, text: 'world' },
    ]
    expect(transcriptTextFromRawTranscript(transcript)).toBe('hello  world')
  })

  it('prefers the latest authoritative entry', () => {
    const transcript = [
      { chunk_index: 0, text: 'old final', correction_stage: 'final' },
      { chunk_index: 0, text: 'user edited', display_text: 'user edited', correction_stage: 'user_edited' },
      { chunk_index: 1, text: 'newer local', correction_stage: 'local' },
    ]
    expect(transcriptTextFromRawTranscript(transcript)).toBe('user edited')
  })

  it('honours an empty user_edited entry and does not fall back to raw_text', () => {
    const transcript = [
      {
        chunk_index: 0,
        text: '',
        display_text: '',
        raw_text: 'raw asr text',
        correction_stage: 'user_edited',
      },
    ]
    expect(transcriptTextFromRawTranscript(transcript)).toBe('')
  })

  it('ignores superseded entries in fallback mode', () => {
    const transcript = [
      { chunk_index: 0, text: 'old final', correction_stage: 'superseded' },
      { chunk_index: 1, text: 'current', correction_stage: 'local' },
    ]
    expect(transcriptTextFromRawTranscript(transcript)).toBe('current')
  })
})

describe('transcriptTextFromContent', () => {
  it('extracts transcript text from content markdown', () => {
    const content = '## 语音转文字\n\n这是转写内容\n\n---\n\n这是笔记'
    expect(transcriptTextFromContent(content)).toBe('这是转写内容')
  })

  it('returns empty if no transcript section', () => {
    expect(transcriptTextFromContent('普通内容')).toBe('')
    expect(transcriptTextFromContent(null)).toBe('')
  })
})

describe('notesFromContent', () => {
  it('extracts notes after separator', () => {
    const content = '## 语音转文字\n\n转写\n\n---\n\n我的笔记'
    expect(notesFromContent(content)).toEqual([
      { type: 'text', content: '我的笔记' },
    ])
  })

  it('returns empty if no notes section', () => {
    expect(notesFromContent('## 语音转文字\n\n转写')).toEqual([])
  })

  it('returns whole content as note when no transcript marker and no transcript', () => {
    expect(notesFromContent('纯笔记内容', false)).toEqual([
      { type: 'text', content: '纯笔记内容' },
    ])
  })

  it('returns empty for null', () => {
    expect(notesFromContent(null)).toEqual([])
  })
})

describe('contentBlocksFromLayout', () => {
  it('filters transcript and ppt blocks', () => {
    const layout: NoteLayoutBlock[] = [
      { id: 't-1', type: 'transcript', content: 'text1' },
      { id: 'p-1', type: 'ppt', src: 'img.png', page: 1 },
      { id: 'n-1', type: 'note', content: 'note1' },
    ]
    const blocks = contentBlocksFromLayout(layout)
    expect(blocks).toHaveLength(2)
    expect(blocks[0]).toEqual({ type: 'text', content: 'text1' })
    expect(blocks[1]).toEqual({ type: 'image', src: 'img.png', page: 1, title: undefined })
  })

  it('returns empty for null', () => {
    expect(contentBlocksFromLayout(null)).toEqual([])
  })
})

describe('notesFromLayout', () => {
  it('filters note blocks with content', () => {
    const layout: NoteLayoutBlock[] = [
      { id: 't-1', type: 'transcript', content: 'text' },
      { id: 'n-1', type: 'note', content: 'note1' },
      { id: 'n-2', type: 'note', content: '<br>' },
      { id: 'n-3', type: 'note' },
    ]
    expect(notesFromLayout(layout)).toEqual([
      { type: 'text', content: 'note1' },
    ])
  })
})

describe('layoutFromNoteParts', () => {
  it('uses contentBlocks when available', () => {
    const blocks = [
      { type: 'text' as const, content: '段落1' },
      { type: 'image' as const, src: 'a.png', page: 1 },
    ]
    const notes: StudentNoteLike[] = [{ type: 'text', content: '笔记' }]
    const layout = layoutFromNoteParts('', blocks, notes)
    expect(layout).toHaveLength(3)
    expect(layout[0]).toEqual({ id: 'transcript-1', type: 'transcript', content: '段落1' })
    expect(layout[1]).toEqual({ id: 'ppt-2', type: 'ppt', src: 'a.png', page: 1, title: undefined })
    expect(layout[2]).toEqual({ id: 'note-3', type: 'note', content: '笔记' })
  })

  it('falls back to transcript text paragraphs', () => {
    const notes: StudentNoteLike[] = []
    const layout = layoutFromNoteParts('第一段\n\n第二段', [], notes)
    expect(layout).toHaveLength(2)
    expect(layout[0]).toEqual({ id: 'transcript-1', type: 'transcript', content: '第一段' })
    expect(layout[1]).toEqual({ id: 'transcript-2', type: 'transcript', content: '第二段' })
  })

  it('filters out empty content blocks', () => {
    const blocks = [
      { type: 'text' as const, content: '' },
      { type: 'text' as const, content: '有内容' },
    ]
    const layout = layoutFromNoteParts('', blocks, [])
    expect(layout).toHaveLength(1)
    expect(layout[0].content).toBe('有内容')
  })
})

describe('fallbackLayoutFromNote', () => {
  it('uses layout_blocks if available', () => {
    const note = {
      layout_blocks: [{ id: 'x', type: 'transcript' as const, content: 'cached' }],
    }
    expect(fallbackLayoutFromNote(note)).toEqual(note.layout_blocks)
  })

  it('falls back to content transcript', () => {
    const note = {
      content: '## 语音转文字\n\n转写文本\n\n---\n\n笔记',
    }
    const layout = fallbackLayoutFromNote(note)
    expect(layout.some((b) => b.content === '转写文本')).toBe(true)
    expect(layout.some((b) => b.content === '笔记')).toBe(true)
  })

  it('falls back to raw transcript', () => {
    const note = {
      transcript: [{ chunk_index: 0, text: 'raw' }],
    }
    const layout = fallbackLayoutFromNote(note)
    expect(layout.some((b) => b.content === 'raw')).toBe(true)
  })
})

describe('slideImageSrc', () => {
  it('prefers image_path over image_base64', () => {
    expect(slideImageSrc({ page: 1, title: 't', text: 'txt', image_path: 'path.png', image_base64: 'b64' })).toBe('path.png')
    expect(slideImageSrc({ page: 1, title: 't', text: 'txt', image_base64: 'b64' })).toBe('b64')
    expect(slideImageSrc(undefined)).toBeUndefined()
  })
})
