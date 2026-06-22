import { useEffect, useRef, useState } from 'react';
import { AuthenticatedImage } from '@/components/AuthenticatedImage';
import { getMediaUrl } from '@/services/api';
import type { Slide, StrokeAnnotation } from '@/services/api/types';
import type { PadStroke } from '@/pages/pad/hooks/usePadAnnotations';

export type AnnotationTool = 'pen' | 'eraser';

interface SlideAnnotationLayerProps {
  sessionId?: string;
  slide?: Slide;
  tool: AnnotationTool;
  color: string;
  width: number;
  strokes: PadStroke[];
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
  tool,
  color,
  width,
  strokes,
  onAddStroke,
  onErase,
  className,
}: SlideAnnotationLayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const drawingRef = useRef(false);
  const currentStrokeRef = useRef<{ color: string; width: number; points: { x: number; y: number }[] } | null>(null);

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
    if (!slide || e.button !== 0) return;
    e.preventDefault();
    const canvas = canvasRef.current;
    if (canvas && 'setPointerCapture' in canvas && typeof canvas.setPointerCapture === 'function') {
      canvas.setPointerCapture(e.pointerId);
    }
    drawingRef.current = true;
    const point = normalizePoint(e);

    if (tool === 'pen') {
      currentStrokeRef.current = { color, width, points: [point] };
      draw();
    } else if (tool === 'eraser') {
      onErase(point, 0.02);
    }
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!slide || !drawingRef.current) return;
    e.preventDefault();
    const point = normalizePoint(e);

    if (tool === 'pen' && currentStrokeRef.current) {
      currentStrokeRef.current.points.push(point);
      draw();
    } else if (tool === 'eraser') {
      onErase(point, 0.02);
    }
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return;
    e.preventDefault();
    const canvas = canvasRef.current;
    if (canvas && 'releasePointerCapture' in canvas && typeof canvas.releasePointerCapture === 'function') {
      try {
        canvas.releasePointerCapture(e.pointerId);
      } catch {
        // ignore
      }
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
      ) : (
        <div className="absolute inset-0 flex items-center justify-center text-slate-400">
          {slide ? '此页无图片' : '请选择幻灯片'}
        </div>
      )}
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
    </div>
  );
}
