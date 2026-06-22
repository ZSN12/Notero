import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, fireEvent } from '@testing-library/react';
import { SlideAnnotationLayer } from '../SlideAnnotationLayer';
import type { PadStroke } from '@/pages/pad/hooks/usePadAnnotations';

vi.mock('@/components/AuthenticatedImage', () => ({
  AuthenticatedImage: ({ alt }: { alt?: string }) => <img alt={alt || 'slide'} data-testid="slide-image" />,
}));

const CANVAS_RECT = { left: 0, top: 0, width: 200, height: 200, right: 200, bottom: 200, x: 0, y: 0, toJSON: () => {} };

function mockCanvasRect(element: HTMLElement) {
  Object.defineProperty(element, 'getBoundingClientRect', {
    value: () => CANVAS_RECT,
  });
}

describe('SlideAnnotationLayer', () => {
  const slide = { page: 1, title: 'Test', text: '', image_path: 'slide1.png' };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('emits a normalized stroke on pointer draw', () => {
    const onAddStroke = vi.fn();
    const { getByTestId } = render(
      <SlideAnnotationLayer
        sessionId="s1"
        slide={slide}
        tool="pen"
        color="#3b82f6"
        width={4}
        strokes={[]}
        onAddStroke={onAddStroke}
        onErase={vi.fn()}
      />
    );

    const canvas = getByTestId('annotation-canvas') as HTMLCanvasElement;
    mockCanvasRect(canvas);

    fireEvent.pointerDown(canvas, { button: 0, clientX: 20, clientY: 40 });
    fireEvent.pointerMove(canvas, { clientX: 60, clientY: 80 });
    fireEvent.pointerUp(canvas, { clientX: 60, clientY: 80 });

    expect(onAddStroke).toHaveBeenCalledTimes(1);
    const stroke = onAddStroke.mock.calls[0][0];
    expect(stroke.type).toBe('stroke');
    expect(stroke.color).toBe('#3b82f6');
    expect(stroke.width).toBe(4);
    expect(stroke.points).toEqual([
      { x: 0.1, y: 0.2 },
      { x: 0.3, y: 0.4 },
    ]);
  });

  it('emits erase events in eraser mode', () => {
    const onErase = vi.fn();
    const existingStroke: PadStroke = {
      id: 's1',
      type: 'stroke',
      color: '#000',
      width: 4,
      points: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
    };
    const { getByTestId } = render(
      <SlideAnnotationLayer
        sessionId="s1"
        slide={slide}
        tool="eraser"
        color="#000"
        width={4}
        strokes={[existingStroke]}
        onAddStroke={vi.fn()}
        onErase={onErase}
      />
    );

    const canvas = getByTestId('annotation-canvas') as HTMLCanvasElement;
    mockCanvasRect(canvas);

    fireEvent.pointerDown(canvas, { button: 0, clientX: 10, clientY: 10 });
    fireEvent.pointerMove(canvas, { clientX: 12, clientY: 12 });

    expect(onErase).toHaveBeenCalled();
    const lastCall = onErase.mock.calls[onErase.mock.calls.length - 1];
    expect(lastCall[0].x).toBeCloseTo(0.06, 2);
    expect(lastCall[0].y).toBeCloseTo(0.06, 2);
    expect(lastCall[1]).toBe(0.02);
  });
});
