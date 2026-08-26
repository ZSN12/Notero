import type { FreeNoteAiBlock, FreeNoteBackground, FreeNoteInsert, FreeNoteReviewStatus, FreeNoteTextBlock, StrokeAnnotation } from '@/services/api/types';

export interface FreeNoteExportPage {
  page: number;
  background: FreeNoteBackground;
  title?: string;
  inserts?: FreeNoteInsert[];
  textBlocks?: FreeNoteTextBlock[];
  aiBlocks?: FreeNoteAiBlock[];
  reviewStatus?: FreeNoteReviewStatus;
  strokes: StrokeAnnotation[];
}

const EXPORT_WIDTH = 1600;
const EXPORT_HEIGHT = 1200;

function drawPaperBackground(ctx: CanvasRenderingContext2D, background: FreeNoteBackground, width: number, height: number) {
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = 'rgba(148, 163, 184, 0.45)';
  ctx.lineWidth = 1;

  if (background === 'grid') {
    const step = 40;
    for (let x = 0; x <= width; x += step) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let y = 0; y <= height; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }
  } else if (background === 'lined') {
    const step = 48;
    for (let y = step; y <= height; y += step) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }
  }
}

function drawStrokes(ctx: CanvasRenderingContext2D, strokes: StrokeAnnotation[], width: number, height: number) {
  for (const stroke of strokes) {
    if (!stroke.points.length) continue;
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

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error('自由笔记插图加载失败'));
    image.src = src;
  });
}

function drawInsertImage(ctx: CanvasRenderingContext2D, image: HTMLImageElement, insert: FreeNoteInsert, width: number, height: number) {
  const x = typeof insert.x === 'number' ? insert.x : 0;
  const y = typeof insert.y === 'number' ? insert.y : 0;
  const insertWidth = typeof insert.width === 'number' ? insert.width : 1;
  const insertHeight = typeof insert.height === 'number' ? insert.height : 1;
  ctx.drawImage(image, x * width, y * height, insertWidth * width, insertHeight * height);
}

function getLinkedSlideNumbers(inserts: FreeNoteInsert[] = []): number[] {
  return Array.from(new Set(
    inserts
      .filter((insert) => insert.type === 'slide_snapshot')
      .map((insert) => (insert.slideIndex ?? -1) + 1)
      .filter((value) => Number.isFinite(value) && value > 0),
  )).sort((a, b) => a - b);
}

function getReviewStatusLabel(status?: FreeNoteReviewStatus) {
  if (status === 'important') return '重点';
  if (status === 'todo') return '待处理';
  if (status === 'reviewed') return '已复习';
  return '';
}

function drawTextBlocks(ctx: CanvasRenderingContext2D, textBlocks: FreeNoteTextBlock[], width: number, height: number) {
  for (const block of textBlocks) {
    const x = block.x * width;
    const y = block.y * height;
    const blockWidth = block.width * width;
    const lineHeight = block.fontSize * 1.35;
    ctx.fillStyle = block.color;
    ctx.font = `${block.fontSize * 2}px sans-serif`;
    const lines = (block.text || '').split('\n');
    lines.forEach((line, index) => {
      ctx.fillText(line, x + 8, y + 8 + lineHeight * 2 * (index + 0.8), blockWidth - 16);
    });
  }
}

export async function renderFreeNotePageToCanvas(page: FreeNoteExportPage, width = EXPORT_WIDTH, height = EXPORT_HEIGHT): Promise<HTMLCanvasElement> {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('无法创建导出画布');
  }
  drawPaperBackground(ctx, page.background, width, height);
  for (const insert of page.inserts ?? []) {
    const image = await loadImage(insert.dataUrl);
    drawInsertImage(ctx, image, insert, width, height);
  }
  drawTextBlocks(ctx, page.textBlocks ?? [], width, height);
  drawStrokes(ctx, page.strokes, width, height);
  return canvas;
}

async function renderFreeNoteReviewPageToCanvas(page: FreeNoteExportPage): Promise<HTMLCanvasElement> {
  const noteCanvas = await renderFreeNotePageToCanvas(page);
  const canvas = document.createElement('canvas');
  canvas.width = EXPORT_WIDTH;
  canvas.height = EXPORT_HEIGHT;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('无法创建导出画布');

  const margin = 48;
  const footerHeight = 72;
  const contentWidth = EXPORT_WIDTH - margin * 2;
  const contentHeight = EXPORT_HEIGHT - margin - footerHeight;

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, EXPORT_WIDTH, EXPORT_HEIGHT);
  ctx.drawImage(noteCanvas, margin, margin, contentWidth, contentHeight);

  const slideNumbers = getLinkedSlideNumbers(page.inserts);
  const statusLabel = getReviewStatusLabel(page.reviewStatus);
  const aiBlocks = page.aiBlocks ?? [];
  if (aiBlocks.length > 0) {
    ctx.fillStyle = '#334155';
    ctx.font = '20px sans-serif';
    ctx.fillText(`AI 内容：${aiBlocks.map((block) => block.title).join(' / ')}`, margin, EXPORT_HEIGHT - 58);
  }
  const footer = `${page.title || `自由笔记 ${page.page}`} · 第 ${page.page} 页${statusLabel ? ` · ${statusLabel}` : ''}${slideNumbers.length ? ` · 关联课件：${slideNumbers.join(', ')}` : ''}`;
  ctx.fillStyle = '#475569';
  ctx.font = '24px sans-serif';
  ctx.fillText(footer, margin, EXPORT_HEIGHT - 28);
  return canvas;
}

export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function exportFreeNotePagePng(page: FreeNoteExportPage, filename: string): Promise<void> {
  return new Promise((resolve, reject) => {
    renderFreeNotePageToCanvas(page).then((canvas) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error('PNG 导出失败'));
        return;
      }
      downloadBlob(blob, filename);
      resolve();
    }, 'image/png');
    }).catch(reject);
  });
}

function dataUrlToBinary(dataUrl: string): string {
  const base64 = dataUrl.split(',')[1] || '';
  if (typeof atob === 'function') return atob(base64);
  const globalBuffer = (globalThis as unknown as { Buffer?: { from: (value: string, encoding: string) => { toString: (encoding: string) => string } } }).Buffer;
  if (globalBuffer) return globalBuffer.from(base64, 'base64').toString('binary');
  throw new Error('当前环境不支持 PDF 编码');
}

function pdfEscape(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)');
}

export async function buildFreeNotesPdfBlob(pages: FreeNoteExportPage[], title = 'free-notes'): Promise<Blob> {
  const rendered = await Promise.all(pages.map(async (page) => ({
    page,
    data: dataUrlToBinary((await renderFreeNoteReviewPageToCanvas(page)).toDataURL('image/jpeg', 0.92)),
  })));
  const objects: string[] = [];
  const addObject = (body: string) => {
    objects.push(body);
    return objects.length;
  };

  const catalogId = addObject('<< /Type /Catalog /Pages 2 0 R >>');
  const pagesId = addObject('');
  const pageIds: number[] = [];
  rendered.forEach(({ data }, index) => {
    const imageId = addObject(
      `<< /Type /XObject /Subtype /Image /Width ${EXPORT_WIDTH} /Height ${EXPORT_HEIGHT} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${data.length} >>\nstream\n${data}\nendstream`
    );
    const content = `q\n595 0 0 446 0 74 cm\n/Im${index + 1} Do\nQ`;
    const contentId = addObject(`<< /Length ${content.length} >>\nstream\n${content}\nendstream`);
    const pageId = addObject(
      `<< /Type /Page /Parent ${pagesId} 0 R /MediaBox [0 0 595 842] /Resources << /XObject << /Im${index + 1} ${imageId} 0 R >> >> /Contents ${contentId} 0 R >>`
    );
    pageIds.push(pageId);
  });
  objects[pagesId - 1] = `<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(' ')}] /Count ${pageIds.length} >>`;

  const infoId = addObject(`<< /Title (${pdfEscape(title)}) /Producer (Notero) >>`);
  let pdf = `%PDF-1.4\n% ${rendered.map(({ page }) => `${page.title || `自由笔记 ${page.page}`} | Page ${page.page} | ${getReviewStatusLabel(page.reviewStatus)} | PPT ${getLinkedSlideNumbers(page.inserts).join(',')} | AI ${(page.aiBlocks ?? []).map((block) => `${block.title}:${block.content}`).join(';')}`).join(' / ')}\n`;
  const offsets = [0];
  objects.forEach((body, index) => {
    offsets.push(pdf.length);
    pdf += `${index + 1} 0 obj\n${body}\nendobj\n`;
  });
  const xrefOffset = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let i = 1; i < offsets.length; i++) {
    pdf += `${String(offsets[i]).padStart(10, '0')} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root ${catalogId} 0 R /Info ${infoId} 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
  return new Blob([pdf], { type: 'application/pdf' });
}

export async function exportFreeNotesPdf(pages: FreeNoteExportPage[], filename: string, title?: string) {
  downloadBlob(await buildFreeNotesPdfBlob(pages, title), filename);
}
