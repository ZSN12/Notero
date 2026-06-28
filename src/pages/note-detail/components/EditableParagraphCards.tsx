import { useRef, useEffect, useMemo, useCallback, useImperativeHandle, forwardRef } from 'react';
import { sanitizeHTML } from '@/lib/sanitize';
import { stableTextId } from '@/lib/sourceAnchors';
import { useEditorHistory } from '@/hooks/useEditorHistory';
import { formatDuration, type ParagraphTimeRange } from '@/services/api';

export interface EditableParagraphCardsHandle {
  undo: () => void;
  redo: () => void;
  getRootElement: () => HTMLDivElement | null;
}

interface EditableParagraphCardsProps {
  transcriptText: string;
  containerRef?: React.RefObject<HTMLDivElement>;
  paragraphTimeRanges?: ParagraphTimeRange[];
  currentTimeMs?: number;
  onSeek?: (startMs: number) => void;
  onUpdateDraft: (value: string) => void;
  onCommitDraft: () => void;
  onMarkUserEdited: () => void;
  onSetActiveTextEl: (el: HTMLDivElement | null) => void;
  onClearSentences: () => void;
}

export const EditableParagraphCards = forwardRef<EditableParagraphCardsHandle, EditableParagraphCardsProps>(
  function EditableParagraphCards(
    {
      transcriptText,
      containerRef: externalContainerRef,
      paragraphTimeRanges,
      currentTimeMs,
      onSeek,
      onUpdateDraft,
      onCommitDraft,
      onMarkUserEdited,
      onSetActiveTextEl,
      onClearSentences,
    },
    ref,
  ) {
    const internalContainerRef = useRef<HTMLDivElement>(null);
    const containerRef = externalContainerRef || internalContainerRef;
    const activeIndexRef = useRef<number | null>(null);
    const isComposingRef = useRef(false);
    const blockRefs = useRef<Map<number, HTMLDivElement>>(new Map());
    // Per-block local drafts so React never rewrites the active block while typing.
    const draftMapRef = useRef<Map<number, string>>(new Map());
    const commitTimerRef = useRef<number | null>(null);
    const history = useEditorHistory();

    const setBlockRef = (index: number) => (el: HTMLDivElement | null) => {
      if (el) blockRefs.current.set(index, el);
      else blockRefs.current.delete(index);
    };

    // Split only on user-created paragraph breaks. Do NOT auto-split long paragraphs
    // into multiple cards, otherwise a simple focus/blur would rewrite persistence.
    const paragraphs = useMemo(() => {
      return transcriptText
        .split('\n\n')
        .map((p) => p.trim())
        .filter((p) => p);
    }, [transcriptText]);

    const getParagraphTimeRange = useCallback(
      (para: string, index: number): ParagraphTimeRange | undefined => {
        if (!paragraphTimeRanges || paragraphTimeRanges.length === 0) return undefined;
        const cleanPara = para.trim();
        const byText = paragraphTimeRanges.find((r) => r.text.trim() === cleanPara);
        if (byText) return byText;
        return paragraphTimeRanges[index];
      },
      [paragraphTimeRanges],
    );

    const readDraftFromDom = useCallback(() => {
      if (!containerRef.current) return transcriptText;
      const parts: string[] = [];
      for (const child of containerRef.current.children) {
        // Cards may be wrapped in a relative container that holds a timestamp
        // badge; the editable block itself is marked with data-transcript-block.
        const block = (child as HTMLElement).querySelector?.('[data-transcript-block]') as HTMLElement | null;
        const html = sanitizeHTML((block ?? child).innerHTML) as unknown as string;
        if (html && html !== '<br>' && html !== '<br />') {
          parts.push(html);
        }
      }
      return parts.join('\n\n');
    }, [transcriptText, containerRef]);

    const hasRecordedInitialRef = useRef(false);
    useEffect(() => {
      if (hasRecordedInitialRef.current) return;
      if (!containerRef.current) return;
      hasRecordedInitialRef.current = true;
      history.record(readDraftFromDom(), true);
    }, [containerRef, history, readDraftFromDom]);

    const commitDraft = useCallback(() => {
      const text = readDraftFromDom();
      draftMapRef.current.clear();
      onUpdateDraft(text);
      onCommitDraft();
    }, [readDraftFromDom, onUpdateDraft, onCommitDraft]);

    const scheduleCommit = useCallback(() => {
      if (commitTimerRef.current) window.clearTimeout(commitTimerRef.current);
      commitTimerRef.current = window.setTimeout(() => {
        commitTimerRef.current = null;
        commitDraft();
      }, 1000);
    }, [commitDraft]);

    const applySnapshot = useCallback(
      (snapshot: string | null) => {
        if (snapshot === null || !containerRef.current) return;
        if (commitTimerRef.current) {
          window.clearTimeout(commitTimerRef.current);
          commitTimerRef.current = null;
        }
        containerRef.current.innerHTML = snapshot
          .split('\n\n')
          .map(
            (html) =>
              `<div data-transcript-block class="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 text-sm text-slate-600 dark:text-slate-300 leading-7 whitespace-pre-wrap break-words shadow-sm outline-none transition-colors hover:border-slate-300 dark:hover:border-slate-600 focus:border-blue-300 dark:focus:border-blue-600 focus:ring-2 focus:ring-blue-100 dark:focus:ring-blue-900/30 select-text cursor-text">${html}</div>`,
          )
          .join('');
        blockRefs.current.clear();
        draftMapRef.current.clear();
        activeIndexRef.current = null;
        onSetActiveTextEl(null);
        onUpdateDraft(snapshot);
        onCommitDraft();
        history.record(snapshot, true);
      },
      [containerRef, history, onCommitDraft, onSetActiveTextEl, onUpdateDraft],
    );

    const handleUndo = useCallback(() => {
      applySnapshot(history.undo());
    }, [applySnapshot, history]);

    const handleRedo = useCallback(() => {
      applySnapshot(history.redo());
    }, [applySnapshot, history]);

    useImperativeHandle(
      ref,
      () => ({
        undo: handleUndo,
        redo: handleRedo,
        getRootElement: () => containerRef.current,
      }),
      [handleUndo, handleRedo, containerRef],
    );

    // Sync non-active blocks when paragraphs change from outside (load / AI / commit).
    useEffect(() => {
      if (!containerRef.current) return;
      paragraphs.forEach((para, index) => {
        if (index === activeIndexRef.current) return;
        const el = blockRefs.current.get(index);
        if (!el) return;
        const next = sanitizeHTML(para.trim()) as unknown as string;
        const draft = draftMapRef.current.get(index);
        const target = draft !== undefined ? draft : next;
        if (el.innerHTML !== target) {
          el.innerHTML = target;
        }
      });
    }, [paragraphs, containerRef]);

    const handleInput = useCallback(() => {
      onMarkUserEdited();
      if (isComposingRef.current) return;
      const index = activeIndexRef.current;
      if (index !== null) {
        const el = blockRefs.current.get(index);
        if (el) {
          draftMapRef.current.set(index, sanitizeHTML(el.innerHTML) as unknown as string);
        }
      }
      const draft = readDraftFromDom();
      onUpdateDraft(draft);
      onClearSentences();
      scheduleCommit();
      history.record(draft);
    }, [history, onClearSentences, onMarkUserEdited, onUpdateDraft, readDraftFromDom, scheduleCommit]);

    useEffect(() => {
      const container = containerRef.current;
      if (!container || typeof MutationObserver === 'undefined') return;

      const observer = new MutationObserver(() => {
        if (activeIndexRef.current === null || isComposingRef.current) return;
        handleInput();
      });
      observer.observe(container, {
        childList: true,
        characterData: true,
        subtree: true,
      });
      return () => observer.disconnect();
    }, [containerRef, handleInput]);

    const handleCompositionStart = () => {
      isComposingRef.current = true;
      onMarkUserEdited();
    };

    const handleCompositionEnd = () => {
      isComposingRef.current = false;
      handleInput();
    };

    const handleBlur = () => {
      if (commitTimerRef.current) {
        window.clearTimeout(commitTimerRef.current);
        commitTimerRef.current = null;
      }
      activeIndexRef.current = null;
      onSetActiveTextEl(null);
      const draft = readDraftFromDom();
      commitDraft();
      history.record(draft, true);
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
      const isMod = e.metaKey || e.ctrlKey;
      if (!isMod) return;
      if (e.key.toLowerCase() === 'z') {
        e.preventDefault();
        if (e.shiftKey) {
          handleRedo();
        } else {
          handleUndo();
        }
      } else if (e.key.toLowerCase() === 'y') {
        e.preventDefault();
        handleRedo();
      }
    };

    return (
      <div ref={containerRef} className="space-y-3" onKeyDown={handleKeyDown}>
        {paragraphs.map((para, i) => {
          const range = getParagraphTimeRange(para, i);
          const hasRange = Boolean(range);
          const isActive =
            hasRange &&
            currentTimeMs !== undefined &&
            currentTimeMs >= (range?.start_ms ?? 0) &&
            currentTimeMs < (range?.end_ms ?? 0);

          const cardClasses = [
            'w-full rounded-xl border px-4 py-3 text-sm leading-7 whitespace-pre-wrap break-words shadow-sm outline-none transition-colors select-text cursor-text',
            isActive
              ? 'border-blue-400 dark:border-blue-500 bg-blue-50 dark:bg-blue-900/20'
              : 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-600',
            'focus:border-blue-300 dark:focus:border-blue-600 focus:ring-2 focus:ring-blue-100 dark:focus:ring-blue-900/30',
          ].join(' ');

          const editable = (
            <div
              key={`para-${i}`}
              ref={setBlockRef(i)}
              data-transcript-block
              data-paragraph-id={stableTextId('transcript', i, para.trim())}
              contentEditable
              suppressContentEditableWarning
              dangerouslySetInnerHTML={{ __html: sanitizeHTML(para.trim()) as unknown as string }}
              onPaste={(e) => {
                e.preventDefault();
                const text = e.clipboardData?.getData('text/plain') || '';
                document.execCommand('insertText', false, text);
              }}
              onInput={handleInput}
              onCompositionStart={handleCompositionStart}
              onCompositionEnd={handleCompositionEnd}
              onBlur={handleBlur}
              onFocus={(e) => {
                activeIndexRef.current = i;
                onSetActiveTextEl(e.currentTarget);
              }}
              onPointerDown={(e) => {
                e.currentTarget.focus();
              }}
              className={cardClasses}
            />
          );

          if (!hasRange) {
            return editable;
          }

          return (
            <div key={`para-wrap-${i}`} className="relative group">
              <button
                type="button"
                onClick={() => range && onSeek?.(range.start_ms)}
                className={`absolute top-2 right-2 z-10 px-1.5 py-0.5 text-[10px] font-medium rounded border transition-colors ${
                  isActive
                    ? 'bg-blue-100 dark:bg-blue-800 text-blue-700 dark:text-blue-200 border-blue-300 dark:border-blue-600'
                    : 'bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400 border-slate-200 dark:border-slate-600 opacity-0 group-hover:opacity-100 focus:opacity-100'
                }`}
                title="跳转到该段落"
              >
                {formatDuration(range!.start_ms)}
              </button>
              {editable}
            </div>
          );
        })}
      </div>
    );
  },
);
