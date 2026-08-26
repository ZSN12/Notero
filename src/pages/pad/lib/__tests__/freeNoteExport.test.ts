import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { buildFreeNotesPdfBlob, exportFreeNotePagePng, renderFreeNotePageToCanvas } from '../freeNoteExport';

const stroke = {
  type: 'stroke' as const,
  color: '#3b82f6',
  width: 4,
  points: [{ x: 0.1, y: 0.1 }, { x: 0.8, y: 0.8 }],
};

describe('freeNoteExport', () => {
  const originalImage = globalThis.Image;
  let fillTextMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fillTextMock = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      fillRect: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      drawImage: vi.fn(),
      fillText: fillTextMock,
      stroke: vi.fn(),
      set fillStyle(_value: string) {},
      set strokeStyle(_value: string) {},
      set lineWidth(_value: number) {},
      set lineCap(_value: string) {},
      set lineJoin(_value: string) {},
      set font(_value: string) {},
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue(`data:image/jpeg;base64,${btoa('jpeg-data')}`);
    vi.spyOn(HTMLCanvasElement.prototype, 'toBlob').mockImplementation(function toBlob(callback) {
      callback(new Blob(['png-data'], { type: 'image/png' }));
    });
    class MockImage {
      naturalWidth = 1600;
      naturalHeight = 1200;
      width = 1600;
      height = 1200;
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_value: string) {
        this.onload?.();
      }
    }
    globalThis.Image = MockImage as unknown as typeof Image;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    globalThis.Image = originalImage;
  });

  it('renders a blank page with the selected paper background', async () => {
    const canvas = await renderFreeNotePageToCanvas({ page: 1, background: 'lined', strokes: [] }, 320, 240);
    expect(canvas.width).toBe(320);
    expect(canvas.height).toBe(240);
  });

  it('builds a multi-page PDF blob', async () => {
    const blob = await buildFreeNotesPdfBlob([
      { page: 1, background: 'grid', strokes: [stroke] },
      { page: 2, background: 'blank', strokes: [] },
    ], '测试自由笔记');
    const text = await blob.text();
    expect(blob.type).toBe('application/pdf');
    expect(text.startsWith('%PDF-1.4')).toBe(true);
    expect(text).toContain('/Count 2');
  });

  it('adds review footer metadata to the PDF export', async () => {
    const blob = await buildFreeNotesPdfBlob([
      {
        page: 1,
        title: 'Formula Review',
        background: 'grid',
        reviewStatus: 'important',
        aiBlocks: [{ id: 'a1', type: 'summary', title: '总结本页', content: 'AI summary content', sourceContext: {}, createdAt: 'now', updatedAt: 'now' }],
        strokes: [],
        inserts: [
          { id: 'i1', type: 'slide_snapshot', slideIndex: 1, dataUrl: 'data:image/png;base64,c2xpZGU=', createdAt: 'now' },
          { id: 'i2', type: 'slide_snapshot', slideIndex: 4, dataUrl: 'data:image/png;base64,c2xpZGU=', createdAt: 'now' },
        ],
      },
    ], 'Review PDF');
    const text = await blob.text();
    expect(text).toContain('Formula Review');
    expect(text).toContain('Page 1');
    expect(text).toContain('重点');
    expect(text).toContain('PPT 2,5');
    expect(text).toContain('总结本页:AI summary content');
  });

  it('renders text blocks into exported PNG canvas', async () => {
    await renderFreeNotePageToCanvas({
      page: 1,
      background: 'blank',
      strokes: [],
      textBlocks: [{
        id: 't1',
        text: '课后重点',
        x: 0.1,
        y: 0.2,
        width: 0.4,
        height: 0.12,
        color: '#1e293b',
        fontSize: 18,
        createdAt: 'now',
        updatedAt: 'now',
      }],
    });
    expect(fillTextMock).toHaveBeenCalledWith('课后重点', expect.any(Number), expect.any(Number), expect.any(Number));
  });

  it('exports current page as PNG through a download blob', async () => {
    const appendSpy = vi.spyOn(document.body, 'appendChild');
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test');
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const clickMock = vi.fn();
    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, 'createElement').mockImplementation((tagName: string, options?: ElementCreationOptions) => {
      const el = originalCreateElement(tagName, options);
      if (tagName === 'a') {
        Object.defineProperty(el, 'click', { value: clickMock });
      }
      return el;
    });

    await exportFreeNotePagePng({ page: 1, background: 'grid', strokes: [] }, 'page.png');
    expect(createObjectURL).toHaveBeenCalled();
    expect(appendSpy).toHaveBeenCalled();
    expect(clickMock).toHaveBeenCalled();

    revokeObjectURL.mockRestore();
  });
});
