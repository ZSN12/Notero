import { memo, useRef, useState, useEffect } from 'react';
import { FileText, Trash2, ChevronUp } from 'lucide-react';
import type { ContentBlock, Slide } from '@/services/api';
import { getMediaUrl } from '@/services/api';
import { sanitizeHTML } from '@/lib/sanitize';
import { AuthenticatedImage } from '@/components/AuthenticatedImage';

interface ContentBlocksViewProps {
  blocks: ContentBlock[];
  slides: Slide[];
  onSetActiveSlideIndex: (index: number) => void;
  onShowLeftPanel: () => void;
  onUpdateContentBlocks: (blocks: ContentBlock[]) => void;
  onUpdateBlockDraft?: (index: number, content: string) => void;
  onCommitContentBlocks?: () => void;
  normalizeTranscriptBlockForDisplay: (content?: string) => string;
  activeTextElRef?: React.MutableRefObject<HTMLDivElement | null>;
  dropTargetIndex?: number | null;
  dropPosition?: 'before' | 'after' | null;
}

function ContentBlocksView({
  blocks,
  slides,
  onSetActiveSlideIndex,
  onShowLeftPanel,
  onUpdateContentBlocks,
  onUpdateBlockDraft,
  onCommitContentBlocks,
  normalizeTranscriptBlockForDisplay,
  activeTextElRef,
  dropTargetIndex,
  dropPosition,
}: ContentBlocksViewProps) {
  const hasImageBlocks = blocks.some((block) => block.type === 'image');
  // Local per-block drafts so the DOM is never rewritten while the user is typing.
  const draftMapRef = useRef<Map<number, string>>(new Map());
  const [activeBlockIndex, setActiveBlockIndex] = useState<number | null>(null);
  const isComposingRef = useRef(false);
  const blockRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  const setBlockRef = (index: number) => (el: HTMLDivElement | null) => {
    if (el) blockRefs.current.set(index, el);
    else blockRefs.current.delete(index);
  };

  // When blocks prop changes from outside (PPT insert, AI restructure, load),
  // sync non-active blocks. The active block keeps its own DOM until blur.
  useEffect(() => {
    blocks.forEach((block, index) => {
      if (block.type !== 'text') return;
      if (index === activeBlockIndex) return;
      const el = blockRefs.current.get(index);
      if (!el) return;
      const next = sanitizeHTML(block.content || '') as unknown as string;
      if (el.innerHTML !== next) {
        el.innerHTML = next;
      }
    });
  }, [blocks, activeBlockIndex]);

  const handleBlockInput = (index: number) => {
    if (isComposingRef.current) return;
    const el = blockRefs.current.get(index);
    if (!el) return;
    const html = sanitizeHTML(el.innerHTML) as unknown as string;
    const normalized = html === '<br>' || html === '<br />' ? '' : html;
    draftMapRef.current.set(index, normalized);
    onUpdateBlockDraft?.(index, normalized);
  };

  const handleCompositionStart = () => {
    isComposingRef.current = true;
  };

  const handleCompositionEnd = (index: number) => {
    isComposingRef.current = false;
    handleBlockInput(index);
  };

  const handleBlockBlur = (index: number) => {
    setActiveBlockIndex(null);
    const el = blockRefs.current.get(index);
    if (el && activeTextElRef) activeTextElRef.current = null;
    // Commit the local draft to parent state so layout_blocks / content are persisted.
    onCommitContentBlocks?.();
  };

  const handleBlockFocus = (index: number, el: HTMLDivElement) => {
    setActiveBlockIndex(index);
    if (activeTextElRef) activeTextElRef.current = el;
  };

  const DropIndicators = ({ blockIndex }: { blockIndex: number }) => {
    if (dropTargetIndex !== blockIndex) return null;
    return (
      <>
        {dropPosition === 'before' && (
          <div className="absolute -top-[3px] left-0 right-0 h-[3px] bg-blue-500 rounded-full z-10 shadow-[0_0_0_2px_rgba(59,130,246,0.2)]" />
        )}
        {dropPosition === 'after' && (
          <div className="absolute -bottom-[3px] left-0 right-0 h-[3px] bg-blue-500 rounded-full z-10 shadow-[0_0_0_2px_rgba(59,130,246,0.2)]" />
        )}
      </>
    );
  };

  const renderTextBlock = (
    textBlock: ContentBlock,
    blockIndex: number,
    wrapperClassName: string,
  ) => {
    const displayContent = normalizeTranscriptBlockForDisplay(textBlock.content);
    return (
      <div key={blockIndex} className="relative">
        <DropIndicators blockIndex={blockIndex} />
        <div
          ref={setBlockRef(blockIndex)}
          data-block-index={blockIndex}
          contentEditable
          suppressContentEditableWarning
          onPointerDown={(e) => { e.currentTarget.focus(); }}
          onPaste={(e) => {
            e.preventDefault();
            const text = e.clipboardData?.getData('text/plain') || '';
            document.execCommand('insertText', false, text);
          }}
          onInput={() => handleBlockInput(blockIndex)}
          onCompositionStart={handleCompositionStart}
          onCompositionEnd={() => handleCompositionEnd(blockIndex)}
          onBlur={() => handleBlockBlur(blockIndex)}
          onFocus={(e) => handleBlockFocus(blockIndex, e.currentTarget)}
          className={wrapperClassName}
          dangerouslySetInnerHTML={{ __html: sanitizeHTML(displayContent) as unknown as string }}
        />
      </div>
    );
  };

  if (!hasImageBlocks) {
    const textBlocks = blocks.filter((block) => block.type === 'text' && (block.content || '').trim());
    return (
      <div className="max-w-none px-1 py-1 text-sm text-slate-600 dark:text-slate-300 leading-8">
        {textBlocks.map((textBlock) => {
          const blockIndex = blocks.indexOf(textBlock);
          const displayContent = normalizeTranscriptBlockForDisplay(textBlock.content);
          const isHeading = /^(课堂笔记|有名管道|无名管道|命名管道|进程|线程|通信|IPC|FIFO|Named Pipe)/i.test(displayContent) && displayContent.length <= 80;
          return renderTextBlock(
            textBlock,
            blockIndex,
            isHeading
              ? 'text-sm font-semibold text-slate-800 dark:text-slate-100 focus:outline-none select-text cursor-text'
              : 'rounded-md border-l-2 border-transparent pl-3 pr-2 py-1 text-slate-600 dark:text-slate-300 whitespace-pre-wrap break-words hover:bg-slate-50/70 dark:hover:bg-slate-800/50 focus:bg-blue-50/50 dark:focus:bg-blue-900/10 focus:border-blue-300 focus:outline-none select-text cursor-text transition-colors',
          );
        })}
      </div>
    );
  }

  const combined: { type: 'combined' | 'text'; imageBlock?: ContentBlock; textBlock?: ContentBlock }[] = [];
  let i = 0;
  while (i < blocks.length) {
    if (blocks[i].type === 'image' && i + 1 < blocks.length && blocks[i + 1].type === 'text') {
      combined.push({ type: 'combined', imageBlock: blocks[i], textBlock: blocks[i + 1] });
      i += 2;
    } else if (blocks[i].type === 'text') {
      combined.push({ type: 'text', textBlock: blocks[i] });
      i++;
    } else {
      i++;
    }
  }

  return (
    <div className="space-y-3">
      {combined.map((group, idx) => {
        if (group.type === 'combined' && group.imageBlock && group.textBlock) {
          const imageBlock = group.imageBlock;
          const textBlock = group.textBlock;
          const textBlockIndex = blocks.indexOf(textBlock);
          return (
            <div key={idx} className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden shadow-sm">
              <div
                className="flex items-center gap-3 p-3 bg-slate-50/50 dark:bg-slate-800/50 border-b border-slate-100 dark:border-slate-700/50 cursor-pointer hover:bg-slate-100/50 dark:hover:bg-slate-700/50 transition-colors"
                onClick={() => {
                  const pageIdx = (imageBlock.page || 1) - 1;
                  if (pageIdx >= 0 && pageIdx < slides.length) {
                    onSetActiveSlideIndex(pageIdx);
                    if (window.innerWidth < 1024) {
                      onShowLeftPanel();
                    }
                  }
                }}
              >
                <AuthenticatedImage
                  src={imageBlock.src?.startsWith('data:') ? imageBlock.src : imageBlock.src ? getMediaUrl(imageBlock.src) : ''}
                  alt={`PPT 第 ${imageBlock.page} 页`}
                  className="w-16 h-12 object-cover rounded-md border border-slate-100 dark:border-slate-600 flex-shrink-0 hover:scale-105 transition-transform"
                  fallback={<div className="w-16 h-12 rounded-md border border-dashed border-slate-200 dark:border-slate-600 flex-shrink-0 bg-slate-50 dark:bg-slate-900" />}
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <FileText className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
                    <span className="text-xs font-semibold text-slate-600 dark:text-slate-300 truncate">
                      PPT 第 {imageBlock.page} 页 · {imageBlock.title}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-0.5">点击查看大图</p>
                </div>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    const imageBlockIndex = blocks.indexOf(imageBlock);
                    const nextBlocks = blocks.filter((_, blockIndex) => blockIndex !== imageBlockIndex);
                    onUpdateContentBlocks(nextBlocks);
                  }}
                  className="min-w-[32px] min-h-[32px] rounded-md text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center justify-center transition-colors"
                  title="移除此 PPT 插入"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
                <ChevronUp className="w-4 h-4 text-slate-400 rotate-90 flex-shrink-0" />
              </div>
              {renderTextBlock(
                textBlock,
                textBlockIndex,
                'p-4 text-sm text-slate-600 dark:text-slate-300 leading-relaxed whitespace-pre-line focus:outline-none min-h-[60px] select-text cursor-text',
              )}
            </div>
          );
        } else if (group.type === 'text' && group.textBlock) {
          const textBlock = group.textBlock;
          const textBlockIndex = blocks.indexOf(textBlock);
          return (
            <div key={idx} className="relative">
              {renderTextBlock(
                textBlock,
                textBlockIndex,
                'w-full p-4 text-sm text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-600 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-200 leading-relaxed whitespace-pre-line min-h-[60px] select-text cursor-text',
              )}
            </div>
          );
        }
        return null;
      })}
    </div>
  );
}

export default memo(ContentBlocksView);
