import { getMediaUrl } from '@/services/api';
import { preloadAuthenticatedImage } from '@/lib/imageCache';
import type { Slide, StrokeAnnotation } from '@/services/api/types';

const SNAPSHOT_WIDTH = 1600;
const SNAPSHOT_HEIGHT = 1200;

function slideImageUrl(slide: Slide | undefined, sessionId: string | undefined): string | null {
  if (!slide) return null;
  if (slide.image_path && sessionId) {
    return getMediaUrl(`/api/media/slides/${sessionId}/${slide.image_path}`);
  }
  if (slide.image_base64) {
    return slide.image_base64;
  }
  return null;
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('课件截图加载失败'));
    image.src = src;
  });
}

function drawContainImage(ctx: CanvasRenderingContext2D, image: HTMLImageElement, width: number, height: number) {
  const imageWidth = image.naturalWidth || image.width;
  const imageHeight = image.naturalHeight || image.height;
  if (!imageWidth || !imageHeight) return;
  const ratio = Math.min(width / imageWidth, height / imageHeight);
  const drawWidth = imageWidth * ratio;
  const drawHeight = imageHeight * ratio;
  ctx.drawImage(image, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight);
}

function drawStrokes(ctx: CanvasRenderingContext2D, strokes: StrokeAnnotation[], width: number, height: number) {
  for (const stroke of strokes) {
    if (stroke.points.length === 0) continue;
    ctx.strokeStyle = stroke.color;
    ctx.lineWidth = stroke.width * 2;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.beginPath();
    ctx.moveTo(stroke.points[0].x * width, stroke.points[0].y * height);
    for (let i = 1; i < stroke.points.length; i++) {
      const point = stroke.points[i];
      ctx.lineTo(point.x * width, point.y * height);
    }
    ctx.stroke();
  }
}

export async function createSlideSnapshotDataUrl(
  slide: Slide | undefined,
  sessionId: string | undefined,
  strokes: StrokeAnnotation[],
): Promise<string> {
  const url = slideImageUrl(slide, sessionId);
  if (!url) throw new Error('当前课件页无法截图');

  const resolvedUrl = await preloadAuthenticatedImage(url);
  if (!resolvedUrl) throw new Error('当前课件页无法截图');

  const image = await loadImage(resolvedUrl);
  const canvas = document.createElement('canvas');
  canvas.width = SNAPSHOT_WIDTH;
  canvas.height = SNAPSHOT_HEIGHT;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('无法创建截图画布');

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, SNAPSHOT_WIDTH, SNAPSHOT_HEIGHT);
  drawContainImage(ctx, image, SNAPSHOT_WIDTH, SNAPSHOT_HEIGHT);
  drawStrokes(ctx, strokes, SNAPSHOT_WIDTH, SNAPSHOT_HEIGHT);
  return canvas.toDataURL('image/png');
}
