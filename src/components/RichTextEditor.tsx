import { useRef, useEffect, forwardRef, useImperativeHandle, useCallback } from 'react';
import { sanitizeHTML } from '@/lib/sanitize';

export interface RichTextEditorHandle {
  getRootElement: () => HTMLDivElement | null;
  focus: () => void;
  blur: () => void;
  undo: () => void;
  redo: () => void;
}

interface RichTextEditorProps {
  value: string;
  onChange: (value: string) => void;
  onFocus?: () => void;
  onBlur?: () => void;
  placeholder?: string;
  className?: string;
}

const MAX_HISTORY_SIZE = 200;

const RichTextEditor = forwardRef<RichTextEditorHandle, RichTextEditorProps>(
  ({ value, onChange, onFocus, onBlur, placeholder, className }, ref) => {
    const editorRef = useRef<HTMLDivElement | null>(null) as React.MutableRefObject<HTMLDivElement | null>;
    const isInternalUpdate = useRef(false);
    const onChangeRef = useRef(onChange);
    const historyRef = useRef<string[]>([]);
    const historyIndexRef = useRef<number>(-1);
    const prevValueRef = useRef(value);

    useEffect(() => {
      onChangeRef.current = onChange;
    }, [onChange]);

    const pushHistory = useCallback((html: string) => {
      const last = historyRef.current[historyIndexRef.current];
      if (last === html) return;
      historyRef.current = historyRef.current.slice(0, historyIndexRef.current + 1);
      historyRef.current.push(html);
      historyIndexRef.current = historyRef.current.length - 1;
      if (historyRef.current.length > MAX_HISTORY_SIZE) {
        historyRef.current.shift();
        historyIndexRef.current--;
      }
    }, []);

    useEffect(() => {
      const safeValue = sanitizeHTML(value || '') as unknown as string;

      if (historyIndexRef.current === -1) {
        pushHistory(safeValue);
        prevValueRef.current = value;
        if (editorRef.current) editorRef.current.innerHTML = safeValue;
        return;
      }

      if (prevValueRef.current !== value) {
        if (!isInternalUpdate.current && editorRef.current && editorRef.current.innerHTML !== safeValue) {
          editorRef.current.innerHTML = safeValue;
        }
        if (!isInternalUpdate.current) {
          pushHistory(safeValue);
        }
        prevValueRef.current = value;
      }
      isInternalUpdate.current = false;
    }, [value, pushHistory]);

    const restoreSnapshot = useCallback((snapshot: string) => {
      isInternalUpdate.current = true;
      if (editorRef.current) {
        editorRef.current.innerHTML = snapshot;
      }
      onChangeRef.current(snapshot);
    }, []);

    useImperativeHandle(
      ref,
      () => ({
        getRootElement: () => editorRef.current,
        focus: () => editorRef.current?.focus(),
        blur: () => editorRef.current?.blur(),
        undo: () => {
          if (historyIndexRef.current > 0) {
            historyIndexRef.current--;
            restoreSnapshot(historyRef.current[historyIndexRef.current]);
          }
        },
        redo: () => {
          if (historyIndexRef.current < historyRef.current.length - 1) {
            historyIndexRef.current++;
            restoreSnapshot(historyRef.current[historyIndexRef.current]);
          }
        },
      }),
      [restoreSnapshot],
    );

    const handleInput = () => {
      if (editorRef.current) {
        const safeValue = sanitizeHTML(editorRef.current.innerHTML) as unknown as string;
        if (editorRef.current.innerHTML !== safeValue) {
          editorRef.current.innerHTML = safeValue;
        }
        onChangeRef.current(safeValue);
      }
    };

    return (
      <div
        ref={(node) => { editorRef.current = node; }}
        contentEditable
        suppressContentEditableWarning
        onInput={handleInput}
        onFocus={onFocus}
        onBlur={onBlur}
        data-placeholder={placeholder}
        className={className || ''}
        style={{
          minHeight: '200px',
          outline: 'none',
        }}
      />
    );
  }
);

RichTextEditor.displayName = 'RichTextEditor';

export default RichTextEditor;
