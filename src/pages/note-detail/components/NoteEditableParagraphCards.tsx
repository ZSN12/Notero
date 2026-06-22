import { useRef, useEffect, useMemo } from 'react';
import { sanitizeHTML } from '@/lib/sanitize';

export interface NoteEditableParagraphCardsProps {
  transcriptText: string;
  containerRef?: React.RefObject<HTMLDivElement>;
  onUpdateDraft: (value: string) => void;
  onCommitDraft: () => void;
  onMarkUserEdited: () => void;
  onSetActiveTextEl: (el: HTMLDivElement | null) => void;
  onClearSentences: () => void;
}

export function NoteEditableParagraphCards({
  transcriptText,
  containerRef: externalContainerRef,
  onUpdateDraft,
  onCommitDraft,
  onMarkUserEdited,
  onSetActiveTextEl,
  onClearSentences,
}: NoteEditableParagraphCardsProps) {
  const internalContainerRef = useRef<HTMLDivElement | null>(null);
  const containerRef = externalContainerRef || internalContainerRef;
  const activeIndexRef = useRef<number | null>(null);
  const isComposingRef = useRef(false);
  const blockRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  const setBlockRef = (index: number) => (el: HTMLDivElement | null) => {
    if (el) blockRefs.current.set(index, el);
    else blockRefs.current.delete(index);
  };

  // Recompute paragraphs only when the external transcriptText changes (commit/load/AI),
  // never while the user is typing.
  const paragraphs = useMemo(() => {
    const rawParagraphs = transcriptText
      .split('\n\n')
      .map((p) => p.trim())
      .filter((p) => p);
    const CARD_MAX_CHARS = 320;
    const splitLongParagraph = (text: string): string[] => {
      if (text.length <= CARD_MAX_CHARS) return [text];
      const sentences = text.split(/(?<=[。！？.!?])/);
      const chunks: string[] = [];
      let current = '';
      for (const s of sentences) {
        if (current && (current + s).replace(/\s/g, '').length > CARD_MAX_CHARS) {
          chunks.push(current.trim());
          current = s;
        } else {
          current += s;
        }
      }
      if (current.trim()) chunks.push(current.trim());
      return chunks.length ? chunks : [text];
    };
    const result: string[] = [];
    for (const p of rawParagraphs) {
      result.push(...splitLongParagraph(p));
    }
    return result;
  }, [transcriptText]);

  // Sync non-active blocks when paragraphs change from outside.
  useEffect(() => {
    paragraphs.forEach((para, index) => {
      if (index === activeIndexRef.current) return;
      const el = blockRefs.current.get(index);
      if (!el) return;
      const next = sanitizeHTML(para.trim()) as unknown as string;
      if (el.innerHTML !== next) {
        el.innerHTML = next;
      }
    });
  }, [paragraphs]);

  const readDraftFromDom = () => {
    if (!containerRef.current) return transcriptText;
    const parts: string[] = [];
    for (const child of containerRef.current.children) {
      const html = sanitizeHTML((child as HTMLElement).innerHTML) as unknown as string;
      if (html && html !== '<br>' && html !== '<br />') {
        parts.push(html);
      }
    }
    return parts.join('\n\n');
  };

  const handleInput = () => {
    onMarkUserEdited();
    if (isComposingRef.current) return;
    onUpdateDraft(readDraftFromDom());
    onClearSentences();
  };

  const handleCompositionStart = () => {
    isComposingRef.current = true;
    onMarkUserEdited();
  };

  const handleCompositionEnd = () => {
    isComposingRef.current = false;
    handleInput();
  };

  const handleBlur = () => {
    activeIndexRef.current = null;
    onSetActiveTextEl(null);
    onUpdateDraft(readDraftFromDom());
    onCommitDraft();
  };

  return (
    <div ref={containerRef} className="space-y-3">
      {paragraphs.map((para, i) => (
        <div
          key={`para-${i}`}
          ref={setBlockRef(i)}
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
            onMarkUserEdited();
            onSetActiveTextEl(e.currentTarget);
          }}
          onPointerDown={(e) => { e.currentTarget.focus(); }}
          className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 text-sm text-slate-600 dark:text-slate-300 leading-7 whitespace-pre-wrap break-words shadow-sm outline-none transition-colors hover:border-slate-300 dark:hover:border-slate-600 focus:border-blue-300 dark:focus:border-blue-600 focus:ring-2 focus:ring-blue-100 dark:focus:ring-blue-900/30 select-text cursor-text"
        />
      ))}
    </div>
  );
}
