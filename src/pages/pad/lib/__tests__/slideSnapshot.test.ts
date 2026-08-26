import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createSlideSnapshotDataUrl } from '../slideSnapshot';

vi.mock('@/services/api', () => ({
  getMediaUrl: (path: string) => `http://localhost${path}`,
}));

vi.mock('@/lib/imageCache', () => ({
  preloadAuthenticatedImage: vi.fn(async (src: string) => src),
}));

const stroke = {
  type: 'stroke' as const,
  color: '#3b82f6',
  width: 4,
  points: [{ x: 0.1, y: 0.2 }, { x: 0.8, y: 0.7 }],
};

describe('slideSnapshot', () => {
  const originalImage = globalThis.Image;

  beforeEach(() => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({
      fillRect: vi.fn(),
      drawImage: vi.fn(),
      beginPath: vi.fn(),
      moveTo: vi.fn(),
      lineTo: vi.fn(),
      stroke: vi.fn(),
      set fillStyle(_value: string) {},
      set strokeStyle(_value: string) {},
      set lineWidth(_value: number) {},
      set lineCap(_value: string) {},
      set lineJoin(_value: string) {},
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,c25hcA==');
    class MockImage {
      naturalWidth = 1600;
      naturalHeight = 1200;
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

  it('creates a slide snapshot that includes slide image and strokes', async () => {
    const dataUrl = await createSlideSnapshotDataUrl(
      { page: 2, title: 'P2', text: '', image_path: 'slide-2.png' },
      's1',
      [stroke],
    );

    expect(dataUrl).toBe('data:image/png;base64,c25hcA==');
  });

  it('fails visibly when the current slide has no image', async () => {
    await expect(createSlideSnapshotDataUrl(undefined, 's1', [])).rejects.toThrow('当前课件页无法截图');
  });
});
