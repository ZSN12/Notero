import { FileText, ChevronUp, ChevronDown } from 'lucide-react';
import { AuthenticatedImage } from '@/components/AuthenticatedImage';
import { getMediaUrl } from '@/services/api';
import type { Slide } from '@/services/api';
import type { usePPT } from '@/pages/note-detail/usePPT';

export interface DragState {
  slide: Slide | null;
  pointer: { x: number; y: number } | null;
  targetIndex: number | null;
  targetPosition: 'before' | 'after' | null;
}

interface PPTPanelProps {
  ppt: ReturnType<typeof usePPT>;
  dragState: DragState;
  sessionId?: string;
  onSlideMouseDown: (slide: Slide) => (e: React.MouseEvent) => void;
  onSlideTouchStart: (slide: Slide) => (e: React.TouchEvent) => void;
  onSlideTouchMove: (e: React.TouchEvent) => void;
  onSlideTouchEnd: () => void;
}

export function PPTPanel({
  ppt,
  dragState,
  sessionId,
  onSlideMouseDown,
  onSlideTouchStart,
  onSlideTouchMove,
  onSlideTouchEnd,
}: PPTPanelProps) {
  const activeSlide = ppt.state.slides[ppt.state.activeSlideIndex];

  return (
    <div className="flex-shrink-0 border-b border-slate-200/60 dark:border-slate-700/60">
      <div className="px-3 py-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <FileText className="w-3.5 h-3.5 text-blue-500" />
          <h3 className="text-xs font-semibold text-slate-600 dark:text-slate-300">PPT</h3>
        </div>
        {ppt.state.slides.length > 0 && (
          <div className="flex items-center gap-1">
            <span className="text-xs text-slate-400 font-mono">
              {ppt.state.activeSlideIndex + 1}/{ppt.state.slides.length}
            </span>
            <button
              onClick={() => ppt.actions.setActiveSlideIndex(Math.max(0, ppt.state.activeSlideIndex - 1))}
              disabled={ppt.state.activeSlideIndex === 0}
              className="min-w-[32px] min-h-[32px] rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-30 transition-colors flex items-center justify-center"
            >
              <ChevronUp className="w-5 h-5" />
            </button>
            <button
              onClick={() =>
                ppt.actions.setActiveSlideIndex(Math.min(ppt.state.slides.length - 1, ppt.state.activeSlideIndex + 1))
              }
              disabled={ppt.state.activeSlideIndex === ppt.state.slides.length - 1}
              className="min-w-[32px] min-h-[32px] rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-30 transition-colors flex items-center justify-center"
            >
              <ChevronDown className="w-5 h-5" />
            </button>
          </div>
        )}
      </div>

      <div className="px-3 pb-3">
        {ppt.state.slides.length > 0 && activeSlide ? (
          <div className="space-y-1.5">
            <div
              className={`rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 select-none ${
                dragState.slide ? 'opacity-60' : 'hover:ring-2 hover:ring-blue-200 cursor-grab active:cursor-grabbing'
              }`}
              onMouseDown={onSlideMouseDown(activeSlide)}
              onTouchStart={onSlideTouchStart(activeSlide)}
              onTouchMove={onSlideTouchMove}
              onTouchEnd={onSlideTouchEnd}
            >
              {(() => {
                const src = activeSlide.image_path
                  ? getMediaUrl(`/api/media/slides/${sessionId}/${activeSlide.image_path}`)
                  : activeSlide.image_base64 || '';
                const fallback = (
                  <div className="flex items-center justify-center h-28 text-xs text-slate-400">无预览图</div>
                );
                return src ? (
                  <AuthenticatedImage
                    src={src}
                    alt={`Slide ${activeSlide.page}`}
                    className="w-full object-cover pointer-events-none"
                    fallback={fallback}
                  />
                ) : (
                  fallback
                );
              })()}
            </div>
            <p className="text-[10px] text-slate-400 text-center">长按或拖拽到右侧段落插入</p>
          </div>
        ) : (
          <div className="flex items-center justify-center h-28 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-dashed border-slate-300 dark:border-slate-600">
            <p className="text-xs text-slate-400">上传PPT后显示</p>
          </div>
        )}
      </div>
    </div>
  );
}
