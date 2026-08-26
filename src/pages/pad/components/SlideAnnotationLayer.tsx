import { useEffect, useRef, useState } from 'react';
import { AuthenticatedImage } from '@/components/AuthenticatedImage';
import { getMediaUrl } from '@/services/api';
import type { FreeNoteInsert, FreeNoteTextBlock, Slide, StrokeAnnotation } from '@/services/api/types';
import type { PadStroke } from '@/pages/pad/hooks/usePadAnnotations';

export type AnnotationTool = 'pen' | 'eraser' | 'text';

interface SlideAnnotationLayerProps {
  sessionId?: string;
  slide?: Slide;
  allowDrawingWithoutSlide?: boolean;
  background?: 'slide' | 'blank' | 'grid' | 'lined';
  tool: AnnotationTool;
  color: string;
  width: number;
  strokes: PadStroke[];
  inserts?: FreeNoteInsert[];
  textBlocks?: FreeNoteTextBlock[];
  selectedInsertId?: string | null;
  selectedTextBlockId?: string | null;
  onSelectInsert?: (insertId: string | null) => void;
  onUpdateInsert?: (insertId: string, patch: Partial<FreeNoteInsert>) => void;
  onSelectTextBlock?: (blockId: string | null) => void;
  onAddTextBlock?: (point: { x: number; y: number }) => string;
  onUpdateTextBlock?: (blockId: string, patch: Partial<FreeNoteTextBlock>) => void;
  onAddStroke: (stroke: StrokeAnnotation) => void;
  onErase: (point: { x: number; y: number }, radius: number) => void;
  className?: string;
}

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

export function SlideAnnotationLayer({
  sessionId,
  slide,
  allowDrawingWithoutSlide = false,
  background = 'slide',
  tool,
  color,
  width,
  strokes,
  inserts = [],
  textBlocks = [],
  selectedInsertId = null,
  selectedTextBlockId = null,
  onSelectInsert,
  onUpdateInsert,
  onSelectTextBlock,
  onAddTextBlock,
  onUpdateTextBlock,
  onAddStroke,
  onErase,
  className,
}: SlideAnnotationLayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const drawingRef = useRef(false);
  const insertEditRef = useRef<{
    mode: 'move' | 'resize';
    insert: FreeNoteInsert;
    startPoint: { x: number; y: number };
  } | null>(null);
  const textMoveRef = useRef<{
    block: FreeNoteTextBlock;
    startPoint: { x: number; y: number };
  } | null>(null);
  const currentStrokeRef = useRef<{ color: string; width: number; points: { x: number; y: number }[] } | null>(null);

  const getInsertLayout = (insert: FreeNoteInsert) => ({
    x: typeof insert.x === 'number' ? insert.x : 0,
    y: typeof insert.y === 'number' ? insert.y : 0,
    width: typeof insert.width === 'number' ? insert.width : 1,
    height: typeof insert.height === 'number' ? insert.height : 1,
  });

  const clampLayout = (layout: { x: number; y: number; width: number; height: number }) => {
    const width = Math.max(0.12, Math.min(1, layout.width));
    const height = Math.max(0.09, Math.min(1, layout.height));
    return {
      width,
      height,
      x: Math.max(0, Math.min(1 - width, layout.x)),
      y: Math.max(0, Math.min(1 - height, layout.y)),
    };
  };

  const findInsertAtPoint = (point: { x: number; y: number }) => {
    for (let i = inserts.length - 1; i >= 0; i--) {
      const insert = inserts[i];
      const layout = getInsertLayout(insert);
      if (
        point.x >= layout.x &&
        point.x <= layout.x + layout.width &&
        point.y >= layout.y &&
        point.y <= layout.y + layout.height
      ) {
        return insert;
      }
    }
    return null;
  };

  const isResizeHandle = (point: { x: number; y: number }, insert: FreeNoteInsert) => {
    const layout = getInsertLayout(insert);
    return point.x >= layout.x + layout.width - 0.06 && point.y >= layout.y + layout.height - 0.06;
  };

  const getTextBlockLayout = (block: FreeNoteTextBlock) => ({
    x: block.x,
    y: block.y,
    width: block.width,
    height: block.height ?? 0.12,
  });

  const findTextBlockAtPoint = (point: { x: number; y: number }) => {
    for (let i = textBlocks.length - 1; i >= 0; i--) {
      const block = textBlocks[i];
      const layout = getTextBlockLayout(block);
      if (
        point.x >= layout.x &&
        point.x <= layout.x + layout.width &&
        point.y >= layout.y &&
        point.y <= layout.y + layout.height
      ) {
        return block;
      }
    }
    return null;
  };

  const draw = () => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx || size.width === 0 || size.height === 0) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const renderStroke = (stroke: PadStroke) => {
      if (stroke.points.length === 0) return;
      ctx.strokeStyle = stroke.color;
      ctx.lineWidth = stroke.width;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      const start = stroke.points[0];
      ctx.moveTo(start.x * size.width, start.y * size.height);
      for (let i = 1; i < stroke.points.length; i++) {
        const p = stroke.points[i];
        ctx.lineTo(p.x * size.width, p.y * size.height);
      }
      ctx.stroke();
    };

    strokes.forEach(renderStroke);

    if (currentStrokeRef.current) {
      renderStroke({
        ...currentStrokeRef.current,
        type: 'stroke',
        id: 'current',
      });
    }
  };

  useEffect(() => {
    draw();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strokes, size]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const resizeCanvas = () => {
      const rect = container.getBoundingClientRect();
      const width = Math.max(0, Math.floor(rect.width));
      const height = Math.max(0, Math.floor(rect.height));
      setSize({ width, height });

      const canvas = canvasRef.current;
      if (!canvas) return;
      const dpr = window.devicePixelRatio || 1;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      canvas.width = Math.max(1, Math.floor(width * dpr));
      canvas.height = Math.max(1, Math.floor(height * dpr));
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }
    };

    resizeCanvas();

    const observer = new ResizeObserver(resizeCanvas);
    observer.observe(container);
    window.addEventListener('orientationchange', resizeCanvas);
    return () => {
      observer.disconnect();
      window.removeEventListener('orientationchange', resizeCanvas);
    };
  }, []);

  const normalizePoint = (e: React.PointerEvent<HTMLCanvasElement>): { x: number; y: number } => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };
    const rect = canvas.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    return { x, y };
  };

  const handlePointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if ((!slide && !allowDrawingWithoutSlide) || e.button !== 0) return;
    e.preventDefault();
    const canvas = canvasRef.current;
    if (canvas && 'setPointerCapture' in canvas && typeof canvas.setPointerCapture === 'function') {
      canvas.setPointerCapture(e.pointerId);
    }
    const point = normalizePoint(e);
    const targetTextBlock = allowDrawingWithoutSlide ? findTextBlockAtPoint(point) : null;
    if (targetTextBlock && onSelectTextBlock && onUpdateTextBlock) {
      onSelectTextBlock(targetTextBlock.id);
      onSelectInsert?.(null);
      textMoveRef.current = { block: targetTextBlock, startPoint: point };
      return;
    }
    if (tool === 'text' && allowDrawingWithoutSlide && onAddTextBlock) {
      const blockId = onAddTextBlock(point);
      onSelectTextBlock?.(blockId);
      onSelectInsert?.(null);
      return;
    }
    const targetInsert = allowDrawingWithoutSlide ? findInsertAtPoint(point) : null;
    if (targetInsert && onSelectInsert && onUpdateInsert) {
      onSelectInsert(targetInsert.id);
      onSelectTextBlock?.(null);
      insertEditRef.current = {
        mode: isResizeHandle(point, targetInsert) ? 'resize' : 'move',
        insert: targetInsert,
        startPoint: point,
      };
      return;
    }
    if (allowDrawingWithoutSlide) {
      onSelectInsert?.(null);
      onSelectTextBlock?.(null);
    }
    drawingRef.current = true;

    if (tool === 'pen') {
      currentStrokeRef.current = { color, width, points: [point] };
      draw();
    } else if (tool === 'eraser') {
      onErase(point, 0.02);
    }
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if ((!slide && !allowDrawingWithoutSlide) || (!drawingRef.current && !insertEditRef.current && !textMoveRef.current)) return;
    e.preventDefault();
    const point = normalizePoint(e);
    if (textMoveRef.current && onUpdateTextBlock) {
      const { block, startPoint } = textMoveRef.current;
      const layout = getTextBlockLayout(block);
      const dx = point.x - startPoint.x;
      const dy = point.y - startPoint.y;
      const next = {
        x: Math.max(0, Math.min(1 - layout.width, layout.x + dx)),
        y: Math.max(0, Math.min(1 - layout.height, layout.y + dy)),
      };
      onUpdateTextBlock(block.id, next);
      textMoveRef.current = { block: { ...block, ...next }, startPoint: point };
      return;
    }
    if (insertEditRef.current && onUpdateInsert) {
      const { mode, insert, startPoint } = insertEditRef.current;
      const layout = getInsertLayout(insert);
      const dx = point.x - startPoint.x;
      const dy = point.y - startPoint.y;
      if (mode === 'move') {
        onUpdateInsert(insert.id, clampLayout({ ...layout, x: layout.x + dx, y: layout.y + dy }));
      } else {
        const ratio = layout.width / Math.max(layout.height, 0.01);
        const rawWidth = Math.max(0.12, layout.width + dx);
        const rawHeight = Math.max(0.09, rawWidth / ratio);
        onUpdateInsert(insert.id, clampLayout({ ...layout, width: rawWidth, height: rawHeight }));
      }
      insertEditRef.current = {
        mode,
        insert: { ...insert, ...getInsertLayout(insert), ...clampLayout(mode === 'move'
          ? { ...layout, x: layout.x + dx, y: layout.y + dy }
          : { ...layout, width: Math.max(0.12, layout.width + dx), height: Math.max(0.09, (layout.width + dx) / (layout.width / Math.max(layout.height, 0.01))) }) },
        startPoint: point,
      };
      return;
    }

    if (tool === 'pen' && currentStrokeRef.current) {
      currentStrokeRef.current.points.push(point);
      draw();
    } else if (tool === 'eraser') {
      onErase(point, 0.02);
    }
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current && !insertEditRef.current && !textMoveRef.current) return;
    e.preventDefault();
    const canvas = canvasRef.current;
    if (canvas && 'releasePointerCapture' in canvas && typeof canvas.releasePointerCapture === 'function') {
      try {
        canvas.releasePointerCapture(e.pointerId);
      } catch {
        // ignore
      }
    }
    if (insertEditRef.current) {
      insertEditRef.current = null;
      return;
    }
    if (textMoveRef.current) {
      textMoveRef.current = null;
      return;
    }
    drawingRef.current = false;

    if (tool === 'pen' && currentStrokeRef.current && currentStrokeRef.current.points.length > 0) {
      onAddStroke({
        type: 'stroke',
        color: currentStrokeRef.current.color,
        width: currentStrokeRef.current.width,
        points: currentStrokeRef.current.points,
      });
      currentStrokeRef.current = null;
      draw();
    }
  };

  const imgUrl = slideImageUrl(slide, sessionId);

  return (
    <div
      ref={containerRef}
      className={`relative w-full h-full overflow-hidden bg-slate-50 dark:bg-slate-900 ${className ?? ''}`}
    >
      {imgUrl ? (
        <AuthenticatedImage
          src={imgUrl}
          alt={slide ? `Slide ${slide.page}` : 'Slide'}
          className="absolute inset-0 w-full h-full object-contain"
          fallback={
            <div className="absolute inset-0 flex items-center justify-center text-slate-400">
              图片加载失败
            </div>
          }
        />
      ) : background === 'grid' || background === 'lined' ? (
        <div
          className="absolute inset-0 bg-white dark:bg-slate-950"
          style={{
            backgroundImage: background === 'grid'
              ? 'linear-gradient(rgba(148, 163, 184, 0.22) 1px, transparent 1px), linear-gradient(90deg, rgba(148, 163, 184, 0.22) 1px, transparent 1px)'
              : 'linear-gradient(rgba(148, 163, 184, 0.24) 1px, transparent 1px)',
            backgroundSize: background === 'grid' ? '28px 28px' : '100% 32px',
          }}
        />
      ) : allowDrawingWithoutSlide ? (
        <div className="absolute inset-0 bg-white dark:bg-slate-950" />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-slate-400">
          {slide ? '此页无图片' : '请选择幻灯片'}
        </div>
      )}
      {inserts.map((insert) => (
        <img
          key={insert.id}
          src={insert.dataUrl}
          alt="课件截图"
          className="absolute object-contain pointer-events-none"
          style={{
            left: `${getInsertLayout(insert).x * 100}%`,
            top: `${getInsertLayout(insert).y * 100}%`,
            width: `${getInsertLayout(insert).width * 100}%`,
            height: `${getInsertLayout(insert).height * 100}%`,
          }}
          draggable={false}
        />
      ))}
      <canvas
        ref={canvasRef}
        data-testid="annotation-canvas"
        className={`absolute inset-0 w-full h-full ${tool === 'pen' ? 'cursor-crosshair' : 'cursor-cell'}`}
        style={{ touchAction: 'none' }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      />
      {inserts.map((insert) => {
        const layout = getInsertLayout(insert);
        const selected = insert.id === selectedInsertId;
        if (!selected) return null;
        return (
          <div
            key={`${insert.id}-selection`}
            className="absolute border-2 border-blue-500 pointer-events-none shadow-[0_0_0_1px_rgba(255,255,255,.9)]"
            style={{
              left: `${layout.x * 100}%`,
              top: `${layout.y * 100}%`,
              width: `${layout.width * 100}%`,
              height: `${layout.height * 100}%`,
            }}
          >
            <span className="absolute -right-2 -bottom-2 w-4 h-4 rounded-full bg-blue-500 border-2 border-white shadow" />
          </div>
        );
      })}
      {textBlocks.map((block) => {
        const layout = getTextBlockLayout(block);
        const selected = block.id === selectedTextBlockId;
        return (
          <div
            key={block.id}
            className="absolute"
            style={{
              left: `${layout.x * 100}%`,
              top: `${layout.y * 100}%`,
              width: `${layout.width * 100}%`,
              height: `${layout.height * 100}%`,
            }}
          >
            <textarea
              value={block.text}
              onFocus={() => {
                onSelectTextBlock?.(block.id);
                onSelectInsert?.(null);
              }}
              onChange={(event) => onUpdateTextBlock?.(block.id, { text: event.target.value })}
              className={`absolute inset-0 w-full h-full resize-none rounded-md bg-white/75 dark:bg-slate-950/70 px-2 py-1 outline-none ${
                selected ? 'ring-2 ring-blue-500' : 'ring-1 ring-transparent hover:ring-slate-300'
              }`}
              style={{
                color: block.color,
                fontSize: `${block.fontSize}px`,
                lineHeight: 1.35,
              }}
            />
            {selected && (
              <span
                className="absolute -left-2 -top-2 w-4 h-4 rounded-full bg-blue-500 border-2 border-white shadow cursor-move"
                onPointerDown={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  const canvas = canvasRef.current;
                  if (event.currentTarget.setPointerCapture) {
                    event.currentTarget.setPointerCapture(event.pointerId);
                  }
                  if (!canvas) return;
                  const rect = canvas.getBoundingClientRect();
                  textMoveRef.current = {
                    block,
                    startPoint: {
                      x: (event.clientX - rect.left) / rect.width,
                      y: (event.clientY - rect.top) / rect.height,
                    },
                  };
                }}
                onPointerMove={(event) => handlePointerMove(event as unknown as React.PointerEvent<HTMLCanvasElement>)}
                onPointerUp={(event) => handlePointerUp(event as unknown as React.PointerEvent<HTMLCanvasElement>)}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
