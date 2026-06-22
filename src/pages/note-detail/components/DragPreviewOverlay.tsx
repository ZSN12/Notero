import { AuthenticatedImage } from '@/components/AuthenticatedImage';
import { getMediaUrl } from '@/services/api';
import type { DragState } from './PPTPanel';

interface DragPreviewOverlayProps {
  dragState: DragState;
  sessionId?: string;
}

export function DragPreviewOverlay({ dragState, sessionId }: DragPreviewOverlayProps) {
  if (!dragState.slide || !dragState.pointer) return null;

  return (
    <div
      className="fixed z-[100] pointer-events-none"
      style={{
        left: dragState.pointer.x + 12,
        top: dragState.pointer.y + 12,
        width: 160,
      }}
    >
      <div className="rounded-lg overflow-hidden border-2 border-blue-400 shadow-xl bg-white dark:bg-slate-900">
        <AuthenticatedImage
          src={
            dragState.slide.image_path
              ? getMediaUrl(`/api/media/slides/${sessionId}/${dragState.slide.image_path}`)
              : dragState.slide.image_base64 || ''
          }
          alt={`Slide ${dragState.slide.page}`}
          className="w-full object-cover"
          fallback={<div className="flex items-center justify-center h-20 text-xs text-slate-400">无预览图</div>}
        />
      </div>
      <div className="mt-1 px-2 py-1 bg-blue-500 text-white text-[10px] rounded-md shadow-md inline-block">
        插入到第 {dragState.slide.page} 页
      </div>
    </div>
  );
}
