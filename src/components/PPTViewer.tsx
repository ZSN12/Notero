import { useState, useCallback, useEffect } from 'react';
import { ChevronUp, ChevronDown, FileText, X } from 'lucide-react';
import { getMediaUrl, Slide } from '@/services/api';
import { AuthenticatedImage } from '@/components/AuthenticatedImage';

interface PPTViewerProps {
  slides: Slide[];
  sessionId?: string;
  onSlideChange?: (pageIndex: number) => void;
  activeSlideIndex?: number;
  onClose?: () => void;
}

function slideImageUrl(slide: Slide, sessionId?: string): string | null {
  // New format: image served from disk via API
  if (slide.image_path && sessionId) {
    return getMediaUrl(`/api/media/slides/${sessionId}/${slide.image_path}`);
  }
  // Legacy format: inline base64
  if (slide.image_base64) {
    return slide.image_base64;
  }
  return null;
}

export default function PPTViewer({
  slides,
  sessionId,
  onSlideChange,
  activeSlideIndex: externalActiveIndex,
  onClose,
}: PPTViewerProps) {
  const [internalIndex, setInternalIndex] = useState(0);
  const activeIndex = externalActiveIndex ?? internalIndex;

  const currentSlide = slides[activeIndex];
  const imgUrl = currentSlide ? slideImageUrl(currentSlide, sessionId) : null;

  const goToPrev = useCallback(() => {
    const newIndex = Math.max(0, activeIndex - 1);
    setInternalIndex(newIndex);
    onSlideChange?.(newIndex);
  }, [activeIndex, onSlideChange]);

  const goToNext = useCallback(() => {
    const newIndex = Math.min(slides.length - 1, activeIndex + 1);
    setInternalIndex(newIndex);
    onSlideChange?.(newIndex);
  }, [activeIndex, slides.length, onSlideChange]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        goToPrev();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        goToNext();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [goToPrev, goToNext]);

  if (!slides.length) {
    return (
      <div className="flex flex-col h-full bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border-r border-slate-200/60 dark:border-slate-700/60">
        <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200/60 dark:border-slate-700/60">
          <div className="flex items-center gap-2">
            <FileText className="w-4 h-4 text-slate-500" />
            <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">PPT</h3>
          </div>
        </div>
        <div className="flex-1 flex flex-col items-center justify-center text-slate-400 dark:text-slate-500 px-4">
          <FileText className="w-10 h-10 mb-3 opacity-40" />
          <p className="text-xs text-center">点击顶部「上传 PPT」按钮上传课件</p>
          <p className="text-xs mt-1 opacity-60 text-center">支持 .ppt / .pptx</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border-r border-slate-200/60 dark:border-slate-700/60">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200/60 dark:border-slate-700/60 flex-shrink-0">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-slate-500" />
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-200">PPT</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 dark:text-slate-400 font-mono">
            {activeIndex + 1} / {slides.length}
          </span>
          {onClose && (
            <button
              onClick={onClose}
              className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Slide Display Area */}
      <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
        <div className="flex-1 flex items-center justify-center p-3 min-h-0 bg-slate-50/50 dark:bg-slate-900/50">
          {imgUrl ? (
            <AuthenticatedImage
              src={imgUrl}
              alt={`Slide ${currentSlide.page}`}
              className="w-full h-full object-contain rounded-lg shadow-sm"
              fallback={
                <div className="flex flex-col items-center justify-center text-slate-400 dark:text-slate-500">
                  <FileText className="w-8 h-8 mb-2 opacity-40" />
                  <p className="text-xs">图片加载失败</p>
                </div>
              }
            />
          ) : (
            <div className="flex flex-col items-center justify-center text-slate-400 dark:text-slate-500">
              <FileText className="w-8 h-8 mb-2 opacity-40" />
              <p className="text-xs">此页无图片</p>
            </div>
          )}
        </div>
      </div>

      {/* Navigation Controls */}
      <div className="flex items-center justify-center gap-3 px-4 py-3 border-t border-slate-200/60 dark:border-slate-700/60 flex-shrink-0 bg-white dark:bg-slate-800">
        <button
          onClick={goToPrev}
          disabled={activeIndex === 0}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronUp className="w-3.5 h-3.5" />
          上一页
        </button>
        <span className="text-xs text-slate-400 dark:text-slate-500 font-mono">
          ↑↓ 翻页
        </span>
        <button
          onClick={goToNext}
          disabled={activeIndex === slides.length - 1}
          className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-700 hover:bg-slate-200 dark:hover:bg-slate-600 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          下一页
          <ChevronDown className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
