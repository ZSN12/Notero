import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchNote, updateNote as apiUpdateNote, insertPPTIntoTranscript, ContentBlock, Slide } from '@/services/api';
import { contentBlocksFromLayout, layoutFromNoteParts, normalizeHtmlText } from '@/lib/noteLayout';

const CORRECTION_POLL_MS = 12000;
const FINAL_CORRECTION_POLL_MS = 2500;
const FINAL_CORRECTION_MAX_ATTEMPTS = 60;
const PPT_INSERT_INITIAL_MS = 8000;
const PPT_INSERT_INTERVAL_MS = 12000;

export interface StudentNote {
  type: string;
  content: string;
}

export interface SentenceWithTime {
  text: string;
  startTime: number;
  endTime: number;
}

export function useTranscript(
  sessionId: string | undefined,
  isRecording: boolean,
  slides: Slide[],
) {
  const [transcriptText, setTranscriptText] = useState('');
  const [sentencesWithTime, setSentencesWithTime] = useState<SentenceWithTime[]>([]);
  const [activeSentenceIndex, setActiveSentenceIndex] = useState<number | null>(null);
  const [isAiRestructuring, setIsAiRestructuring] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const [contentBlocks, setContentBlocks] = useState<ContentBlock[]>([]);
  const [lastSaveTime, setLastSaveTime] = useState<number | null>(null);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);
  const [isPptMatching, setIsPptMatching] = useState(false);
  const [pptMatchMessage, setPptMatchMessage] = useState<string | null>(null);
  const [pendingAiText, setPendingAiText] = useState<string | null>(null);
  const [loadedNote, setLoadedNote] = useState<any>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const [hasLocalChanges, setHasLocalChanges] = useState(false);
  const [partialText, setPartialText] = useState('');
  const [streamingFinals, setStreamingFinals] = useState<string[]>([]);
  const [editorFocused, setEditorFocused] = useState(false);
  const prevTranscriptRef = useRef('');
  const userEditedRef = useRef(false);
  const hasLocalChangesRef = useRef(false);
  const streamChunksRef = useRef<Map<string, string>>(new Map());
  const getCurrentNotesRef = useRef<(() => StudentNote[]) | null>(null);
  const saveTimeoutRef = useRef<number | null>(null);

  const markLocalChanged = useCallback((isUserEdit = true) => {
    if (isUserEdit) userEditedRef.current = true;
    hasLocalChangesRef.current = true;
    setHasLocalChanges(true);
    setSaveStatus('idle');
  }, []);

  const normalizeEditableHtml = useCallback((s: string) => normalizeHtmlText(s), []);

  const dedupeKey = useCallback((value: string) => {
    return normalizeEditableHtml(value)
      .toLowerCase()
      // eslint-disable-next-line no-useless-escape, no-empty-character-class
      .replace(/[\]\[\s，。！？,.!?；;：:、"'“”‘’（）()《》<>【—_-]+/g, '');
  }, [normalizeEditableHtml]);

  const isRepeatedText = useCallback((candidate: string, previous: string) => {
    const cand = dedupeKey(candidate);
    const prev = dedupeKey(previous);
    if (cand.length < 6 || prev.length < 6) return false;
    if (cand === prev) return true;
    const [shorter, longer] = cand.length <= prev.length ? [cand, prev] : [prev, cand];
    if (shorter.length >= 8 && longer.includes(shorter)) {
      return shorter.length / longer.length >= 0.55 || longer.length - shorter.length <= 10;
    }
    const overlap = Array.from(shorter).filter((char) => longer.includes(char)).length / shorter.length;
    if (shorter.length <= 20) return overlap >= 0.78;
    return overlap >= 0.88;
  }, [dedupeKey]);

  const cleanTranscriptText = useCallback((value: string) => {
    return normalizeEditableHtml(value)
      .replace(/^(##\s*语音转文字\s*)+/g, '')
      .replace(/(?:\n\s*)?---+\s*$/g, '')
      .replace(/^[-\s]+$/g, '')
      .trim();
  }, [normalizeEditableHtml]);

  const transcriptFromBlocks = useCallback((blocks: ContentBlock[]) => {
    return blocks
      .filter((block) => block.type === 'text')
      .map((block) => normalizeEditableHtml(block.content || ''))
      .filter(Boolean)
      .join('\n\n');
  }, [normalizeEditableHtml]);

  const getCurrentTranscript = useCallback(() => {
    const blockText = transcriptFromBlocks(contentBlocks);
    return cleanTranscriptText(blockText || transcriptText);
  }, [cleanTranscriptText, contentBlocks, transcriptFromBlocks, transcriptText]);

  const updateTranscriptText = useCallback((value: string, markUserEdit = true) => {
    if (markUserEdit) markLocalChanged(true);
    else setSaveStatus('idle');
    setTranscriptText(value);
  }, [markLocalChanged]);

  const clearStreamingTranscriptChunks = useCallback(() => {
    streamChunksRef.current.clear();
  }, []);

  const upsertStreamingTranscriptChunk = useCallback((chunkId: string, text: string) => {
    const cleaned = text.trim();
    if (!chunkId || !cleaned) return;
    markLocalChanged(false);
    setSentencesWithTime([]);
    setActiveSentenceIndex(null);
    streamChunksRef.current.set(chunkId, cleaned);
    const dedupedParts: string[] = [];
    for (const part of Array.from(streamChunksRef.current.values()).filter(Boolean)) {
      if (dedupedParts.some(prev => isRepeatedText(part, prev))) continue;
      dedupedParts.push(part);
    }
    setTranscriptText(dedupedParts.join('\n\n'));
  }, [isRepeatedText, markLocalChanged]);

  const updateContentBlocks = useCallback((blocks: ContentBlock[], markUserEdit = true, markLocalChange = markUserEdit) => {
    if (markLocalChange) markLocalChanged(markUserEdit);
    else setSaveStatus('idle');
    setContentBlocks(blocks);
  }, [markLocalChanged]);

  const updateContentBlockDraft = useCallback((index: number, content: string) => {
    setContentBlocks((prev) => {
      const block = prev[index];
      if (!block || block.type !== 'text') return prev;
      const next = [...prev];
      next[index] = { ...block, content };
      return next;
    });
    markLocalChanged(true);
  }, [markLocalChanged]);

  const commitContentBlockDraft = useCallback(() => {
    // Draft is already committed to state on input; no extra sync needed.
  }, []);

  const updateTranscriptDraft = useCallback((value: string) => {
    setTranscriptText(value);
  }, []);

  const commitTranscriptDraft = useCallback(() => {
    // transcriptText already reflects the latest draft.
  }, []);

  const setGetCurrentNotes = useCallback((getter: () => StudentNote[]) => {
    getCurrentNotesRef.current = getter;
  }, []);

  const clearPartialText = useCallback(() => {
    setPartialText('');
  }, []);

  const clearDerivedTranscriptViews = useCallback((keepPptBlocks = false) => {
    setSentencesWithTime([]);
    setActiveSentenceIndex(null);
    if (!keepPptBlocks) {
      setContentBlocks([]);
    }
  }, []);

  const clearContentBlocks = useCallback(() => setContentBlocks([]), []);

  // ── WebSocket streaming actions ──
  const receivePartial = useCallback((text: string) => {
    setPartialText(text);
  }, []);

  const receiveFinal = useCallback((text: string) => {
    setPartialText('');
    const trimmed = text.trim();
    if (!trimmed) return;
    setTranscriptText(prev => {
      const prevTrimmed = prev.trim();
      if (!prevTrimmed) return trimmed;

      const appendInline = (base: string, next: string) => {
        const needsSpace = /[A-Za-z0-9]$/.test(base) && /^[A-Za-z0-9]/.test(next);
        return `${base}${needsSpace ? ' ' : ''}${next}`;
      };
      const parts = prevTrimmed.split(/\n{2,}/).filter(Boolean);
      const lastPart = parts[parts.length - 1] || '';
      const lastNorm = lastPart.trim().replace(/\s/g, '');
      const newNorm = trimmed.replace(/\s/g, '');

      // Exact duplicate of the last paragraph — drop it.
      if (lastNorm.length >= 6 && newNorm.length >= 6 && lastNorm === newNorm) {
        return prev;
      }

      // The ASR may emit a cumulative final that extends the last paragraph
      // (e.g. streaming model returns the whole sentence on silence). In that
      // case replace the last paragraph instead of appending a duplicate prefix.
      if (lastNorm.length >= 6 && newNorm.length > lastNorm.length && newNorm.startsWith(lastNorm)) {
        parts[parts.length - 1] = trimmed;
        return parts.join('\n\n');
      }

      // The ASR may also revise the end of the last paragraph. If the new text
      // is mostly the same prefix with a different suffix, replace it.
      if (lastNorm.length >= 6 && newNorm.length >= 6) {
        const commonPrefixLen = Array.from(newNorm).findIndex((_, i) => newNorm[i] !== lastNorm[i]);
        if (commonPrefixLen >= 6 && commonPrefixLen / Math.min(lastNorm.length, newNorm.length) >= 0.6) {
          parts[parts.length - 1] = trimmed;
          return parts.join('\n\n');
        }
      }

      // Realtime ASR should feel like one live transcript line. Paragraph
      // structure is applied later by the final AI/local cleanup step.
      parts[parts.length - 1] = appendInline(lastPart.trim(), trimmed);
      return parts.join('\n\n');
    });
    setStreamingFinals(prev => [...prev, trimmed]);
    markLocalChanged(false);
    setSentencesWithTime([]);
    setActiveSentenceIndex(null);
  }, [markLocalChanged]);

  const clearStreamingState = useCallback(() => {
    setPartialText('');
    setStreamingFinals([]);
  }, []);

  const receiveAiText = useCallback((value: string, options?: { force?: boolean }) => {
    const nextText = value.trim();
    if (!nextText) return;
    if (userEditedRef.current && !options?.force) {
      setPendingAiText(nextText);
      return;
    }
    // Decide whether to replace UI text with corrected DB text.
    // Correction often changes individual characters (length ≈ same)
    // while restructure adds human-friendly formatting (length grows).
    // Previously the 1.1× length gate rejected same-length corrections.
    setTranscriptText(prev => {
      const prevTrimmed = prev.trim();
      if (!prevTrimmed || options?.force) {
        clearDerivedTranscriptViews();
        markLocalChanged(false);
        return nextText;
      }
      // If lengths are close (within ±15%), it's a correction — accept.
      // If DB is longer, it's a restructure — accept.
      // If DB is significantly shorter, reject (stale snapshot).
      if (nextText.length >= prevTrimmed.length * 0.85) {
        // Replace UI text but keep PPT image blocks alive
        clearDerivedTranscriptViews(true);
        markLocalChanged(false);
        return nextText;
      }
      // DB text is much shorter — stale snapshot, keep live UI text
      return prev;
    });
  }, [clearDerivedTranscriptViews, markLocalChanged]);

  const parseSentencesWithTime = useCallback((note: any): SentenceWithTime[] => {
    if (!note?.transcript || !Array.isArray(note.transcript) || note.transcript.length === 0) return [];

    const transcriptSourceText = (chunk: any) => chunk.raw_text || chunk.text || '';
    const sortedChunks = note.transcript
      .sort((a: any, b: any) => (a.chunk_index || 0) - (b.chunk_index || 0))
      .filter((chunk: any) => transcriptSourceText(chunk).trim());

    if (sortedChunks.length === 0) return [];

    const fullText = sortedChunks.map(transcriptSourceText).join(' ').trim();

    // Build timestamp array with sequential position tracking to correctly handle
    // duplicate words (e.g. "的", "是", "在" appear many times in Chinese text).
    // Using indexOf(word, searchPos) ensures each occurrence maps to its actual position.
    const allTimestamps: { text: string; start: number; end: number; pos: number }[] = [];
    let searchPos = 0;
    for (const chunk of sortedChunks) {
      if (chunk.timestamps && Array.isArray(chunk.timestamps)) {
        for (const ts of chunk.timestamps) {
          const word = (ts.text || '').trim();
          if (!word) continue;
          const pos = fullText.indexOf(word, searchPos);
          if (pos !== -1) {
            allTimestamps.push({ text: word, start: ts.start || 0, end: ts.end || 0, pos });
            searchPos = pos + word.length;
          }
        }
      }
    }

    if (allTimestamps.length === 0) return [];

    // Split full text into sentences
    const sentenceRegex = /([^。！？.!?]+[。！？.!?]?)/g;
    const sentences: { text: string; startIdx: number; endIdx: number }[] = [];
    let match;
    while ((match = sentenceRegex.exec(fullText)) !== null) {
      const sentenceText = match[1].trim();
      if (sentenceText) {
        sentences.push({ text: sentenceText, startIdx: match.index, endIdx: match.index + match[1].length });
      }
    }

    // Map each sentence to its time range using the position-matched timestamps
    const result: SentenceWithTime[] = [];
    for (const sentence of sentences) {
      const wordsInRange = allTimestamps.filter(ts =>
        ts.pos >= sentence.startIdx && ts.pos < sentence.endIdx
      );

      if (wordsInRange.length > 0) {
        result.push({
          text: sentence.text,
          startTime: Math.min(...wordsInRange.map(w => w.start)),
          endTime: Math.max(...wordsInRange.map(w => w.end)),
        });
      } else if (result.length > 0) {
        // Fallback: estimate time range from previous sentence
        const prev = result[result.length - 1];
        result.push({
          text: sentence.text,
          startTime: prev.endTime,
          endTime: prev.endTime + 2,
        });
      } else {
        // First sentence(s) have no timestamp match — use the first available timestamp
        result.push({
          text: sentence.text,
          startTime: allTimestamps[0]?.start ?? 0,
          endTime: (allTimestamps[0]?.start ?? 0) + 2,
        });
      }
    }

    return result;
  }, []);

  const transcriptTextFromNote = useCallback((note: any) => {
    if (!note?.transcript || !Array.isArray(note.transcript) || note.transcript.length === 0) return '';
    return [...note.transcript]
      .sort((a: any, b: any) => (a.chunk_index || 0) - (b.chunk_index || 0))
      .map((chunk: any) => chunk.display_text || chunk.corrected_text || chunk.text || chunk.raw_text || '')
      .filter(Boolean)
      .join('\n\n')
      .trim();
  }, []);

  const appendTranscriptText = useCallback((newText: string, skipDedup = false) => {
    markLocalChanged(false);
    setSentencesWithTime([]);
    setActiveSentenceIndex(null);
    setTranscriptText(prev => {
      const trimmed = newText.trim();
      if (!trimmed) return prev;
      const prevTrimmed = prev.trim();

      if (!skipDedup) {
        // Sentence-level dedup against recent chunks, not just paragraph-level.
        // ASR can emit the same sentence twice inside adjacent windows.
        const prevSentences = prevTrimmed
          .split(/(?<=[。！？.!?\n])/)
          .map(s => s.trim())
          .filter(Boolean)
          .slice(-8);
        if (prevSentences.some(s => isRepeatedText(trimmed, s))) {
          return prev;
        }

        const recentParts = prevTrimmed.split(/\n{2,}/).filter(Boolean).slice(-3);
        if (recentParts.some((part) => isRepeatedText(trimmed, part))) {
          return prev;
        }
      }

      return prevTrimmed ? `${prevTrimmed}\n\n${trimmed}` : trimmed;
    });
  }, [isRepeatedText, markLocalChanged]);

  const loadHistory = useCallback(async () => {
    if (!sessionId) return;
    const currentId = sessionId;
    setIsLoaded(false);
    setLoadedNote(null);
    try {
      const note = await fetchNote(sessionId);
      if (sessionId !== currentId) return; // ignore stale response
      if (note) {
        setLoadedNote(note); // Share with parent so it can skip its own fetch
        // Restore transcript priority:
        // 1. User-edited note.content (starts with the transcript marker).
        //    This keeps manual edits/deletes and supports intentionally empty transcripts.
        // 2. Legacy note.content without the marker.
        // 3. Final backend transcript from ASR/AI finalization.
        // 4. Other backend transcript entries.
        let transcriptRestored = false;
        const backendTranscript = transcriptTextFromNote(note);
        const hasFinalTranscript = note.transcript?.some?.(
          (chunk: any) => chunk.correction_stage === 'final',
        );
        if (typeof note.content === 'string' && note.content.startsWith('## 语音转文字\n\n')) {
          const match = note.content.match(/^## 语音转文字\n\n([\s\S]*?)(?:\n\n---\n\n[\s\S]*)?$/);
          const contentTranscript = match ? cleanTranscriptText(match[1] || '') : '';
          setTranscriptText(contentTranscript);
          transcriptRestored = true;
        } else if (note.content) {
          // Fallback: content exists but doesn't match expected format
          const fallbackText = cleanTranscriptText(note.content);
          if (fallbackText) {
            setTranscriptText(fallbackText);
            transcriptRestored = true;
          }
        }
        if (!transcriptRestored && hasFinalTranscript && backendTranscript) {
          setTranscriptText(cleanTranscriptText(backendTranscript));
          transcriptRestored = true;
        }
        if (!transcriptRestored && note.transcript && Array.isArray(note.transcript) && note.transcript.length > 0) {
          const fullTranscript = backendTranscript;
          if (fullTranscript) {
            setTranscriptText(cleanTranscriptText(fullTranscript));
          }
        }
        // Parse sentence-time mapping from transcript JSON (always needs note.transcript)
        if (note.transcript && Array.isArray(note.transcript) && note.transcript.length > 0) {
          const parsed = parseSentencesWithTime(note);
          if (parsed.length > 0) setSentencesWithTime(parsed);
        }
        const restoredBlocks = contentBlocksFromLayout(note.layout_blocks);
        if (restoredBlocks.length > 0) {
          updateContentBlocks(restoredBlocks, false);
          const layoutText = transcriptFromBlocks(restoredBlocks);
          // Only override transcriptText from layout_blocks if we haven't already
          // restored a final transcript, and the layout text is actually newer/non-empty.
          if (layoutText && !transcriptRestored) {
            setTranscriptText(cleanTranscriptText(layoutText));
          }
        } else if (note.ppt_images && note.ppt_images.length > 0) {
          setTimeout(async () => {
            try {
              const blocks = await insertPPTIntoTranscript(sessionId);
              if (blocks.blocks?.some((b: ContentBlock) => b.type === 'image')) {
                updateContentBlocks(blocks.blocks, false, false);
              }
            } catch { /* ignore */ }
          }, 500);
        }
      }
    } catch (error: any) {
      // Missing note is a normal empty-state, not a load failure.
      const isMissingNote =
        error?.message?.includes('404') ||
        error?.message?.includes('Not found') ||
        error?.message?.includes('Note not found');
      if (!isMissingNote) {
        console.error('Failed to load history:', error);
      }
    }
    finally {
      hasLocalChangesRef.current = false;
      setHasLocalChanges(false);
      setIsLoaded(true);
    }
  }, [cleanTranscriptText, sessionId, parseSentencesWithTime, transcriptFromBlocks, transcriptTextFromNote, updateContentBlocks]);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const saveContent = useCallback(async (currentNotes: StudentNote[], forceRetry = false) => {
    if (!sessionId) return false;
    if (!forceRetry && !hasLocalChangesRef.current) return true;
    const cleanTranscript = cleanTranscriptText(getCurrentTranscript());
    const notesContent = currentNotes.map(n => normalizeEditableHtml(n.content)).filter(Boolean).join('\n\n');

    // Always keep the transcript marker so we can distinguish "user saved an empty
    // transcript" from "content was never set" when the note is reloaded.
    const fullContent = `## 语音转文字\n\n${cleanTranscript}\n\n---\n\n${notesContent}`.trim();
    const layoutBlocks = layoutFromNoteParts(cleanTranscript, contentBlocks, currentNotes);
    if (fullContent || currentNotes.length > 0) {
      setSaveStatus('saving');
      setSaveError(null);
      try {
        const result = await apiUpdateNote(sessionId, fullContent, layoutBlocks);
        if (!result) {
          throw new Error('保存失败，服务器未返回数据，请检查网络后重试');
        }
        setLastSaveTime(Date.now());
        setSaveStatus('saved');
        hasLocalChangesRef.current = false;
        setHasLocalChanges(false);
        return true;
      } catch (error: any) {
        console.error('[NoteDetail] Failed to save content:', error);
        setSaveStatus('error');
        setSaveError(error?.message || '保存失败，请检查网络后重试');
        return false;
      }
    }
    hasLocalChangesRef.current = false;
    setHasLocalChanges(false);
    return true;
  }, [cleanTranscriptText, contentBlocks, getCurrentTranscript, normalizeEditableHtml, sessionId]);

  const scheduleSave = useCallback((getCurrentNotes: () => StudentNote[], delay = 300) => {
    getCurrentNotesRef.current = getCurrentNotes;
    if (saveTimeoutRef.current) {
      window.clearTimeout(saveTimeoutRef.current);
      saveTimeoutRef.current = null;
    }
    saveTimeoutRef.current = window.setTimeout(() => {
      saveContent(getCurrentNotes());
    }, delay);
  }, [saveContent]);

  useEffect(() => {
    if (!isRecording || !sessionId) return;
    const interval = setInterval(async () => {
      try {
        const note = await fetchNote(sessionId);
        if (note?.transcript && Array.isArray(note.transcript) && note.transcript.length > 0) {
          const corrected = transcriptTextFromNote(note);
          if (corrected.trim() && corrected.trim() !== transcriptText.trim()) {
            receiveAiText(corrected);
            setIsAiRestructuring(false);
            // Re-parse sentence-time mapping: AI restructured text changed,
            // old sentence boundaries no longer match
            const parsed = parseSentencesWithTime(note);
            if (parsed.length > 0) setSentencesWithTime(parsed);
          }
        }
      } catch { /* ignore */ }
    }, CORRECTION_POLL_MS);
    return () => clearInterval(interval);
  }, [isRecording, sessionId, transcriptText, parseSentencesWithTime, receiveAiText, transcriptTextFromNote]);

  useEffect(() => {
    if (!isRecording && sessionId && transcriptText) {
      prevTranscriptRef.current = transcriptText;
      setIsTranscribing(true);
    }
  }, [isRecording, sessionId]);

  useEffect(() => {
    if (!isTranscribing || isRecording || !sessionId) return;

    let attempts = 0;
    let stopped = false;

    const pollFinalTranscript = async () => {
      if (stopped) return;
      attempts += 1;
      try {
        const note = await fetchNote(sessionId);
        const corrected = transcriptTextFromNote(note);
        const hasFinalTranscript = note?.transcript?.some?.(
          (chunk: any) => chunk.correction_stage === 'final',
        );

        if (hasFinalTranscript) {
          stopped = true;
          if (corrected && corrected.trim() && corrected.trim() !== prevTranscriptRef.current.trim()) {
            receiveAiText(corrected, { force: true });
            const parsed = parseSentencesWithTime(note);
            if (parsed.length > 0) setSentencesWithTime(parsed);
          } else {
            setIsTranscribing(false);
          }
          return;
        }
      } catch { /* ignore */ }

      if (attempts >= FINAL_CORRECTION_MAX_ATTEMPTS) {
        stopped = true;
        setIsTranscribing(false);
      }
    };

    const interval = setInterval(pollFinalTranscript, FINAL_CORRECTION_POLL_MS);
    pollFinalTranscript();
    return () => {
      stopped = true;
      clearInterval(interval);
    };
  }, [isTranscribing, isRecording, sessionId, parseSentencesWithTime, receiveAiText, transcriptTextFromNote]);

  useEffect(() => {
    if (!isTranscribing) return;
    if (transcriptText && transcriptText !== prevTranscriptRef.current) {
      prevTranscriptRef.current = transcriptText;
      setIsTranscribing(false);
      // 转录重组完成，用干净文本重新匹配 PPT
      if (sessionId) {
        setIsPptMatching(true);
        setPptMatchMessage('正在重新匹配 PPT');
        insertPPTIntoTranscript(sessionId).then(result => {
          if (result.blocks?.some((b: ContentBlock) => b.type === 'image')) {
            updateContentBlocks(result.blocks, false, true);
            const count = result.blocks.filter((b) => b.type === 'image').length;
            setPptMatchMessage(count > 0 ? `已匹配 ${count} 页 PPT` : '未匹配到 PPT 页面');
          }
        }).catch(() => {
          setPptMatchMessage('PPT 匹配失败，可稍后重试');
        }).finally(() => setIsPptMatching(false));
      }
    }
  }, [isTranscribing, transcriptText, sessionId, updateContentBlocks]);

  // Auto-save before page unload to prevent data loss when user navigates away
  useEffect(() => {
    const handler = () => {
      if (hasLocalChangesRef.current && sessionId) {
        const token = localStorage.getItem('notero_token');
        const cleanTranscript = cleanTranscriptText(getCurrentTranscript());
        const payload = JSON.stringify({ content: `## 语音转文字\n\n${cleanTranscript}` });
        try {
          const xhr = new XMLHttpRequest();
          xhr.open('PUT', `/api/notes/session/${sessionId}`, false);
          xhr.setRequestHeader('Content-Type', 'application/json');
          if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
          xhr.send(payload);
        } catch { /* ignore */ }
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [sessionId, cleanTranscriptText, getCurrentTranscript]);

  useEffect(() => {
    if (!isRecording || !sessionId || slides.length === 0) return;
    const doInsert = async () => {
      // If the user has manually edited or inserted blocks (e.g. drag-to-insert),
      // don't overwrite their work with automatic matching.
      if (userEditedRef.current) {
        setPptMatchMessage(null);
        return;
      }
      setIsPptMatching(true);
      setPptMatchMessage('正在匹配 PPT');
      try {
        const result = await insertPPTIntoTranscript(sessionId);
        if (result.blocks?.some((b: ContentBlock) => b.type === 'image')) {
          updateContentBlocks(result.blocks, false, true);
          const count = result.blocks.filter((b) => b.type === 'image').length;
          setPptMatchMessage(count > 0 ? `已匹配 ${count} 页 PPT` : '未匹配到 PPT 页面');
        }
      } catch {
        setPptMatchMessage('PPT 匹配失败，可稍后重试');
      } finally {
        setIsPptMatching(false);
      }
    };
    const t1 = setTimeout(doInsert, PPT_INSERT_INITIAL_MS);
    const t2 = setInterval(doInsert, PPT_INSERT_INTERVAL_MS);
    return () => { clearTimeout(t1); clearInterval(t2); };
  }, [isRecording, sessionId, slides.length]);

  useEffect(() => {
    if (isRecording && slides.length > 0) {
      const t = setTimeout(() => setIsAiRestructuring(true), PPT_INSERT_INITIAL_MS);
      return () => clearTimeout(t);
    } else {
      setIsAiRestructuring(false);
    }
  }, [isRecording, slides.length]);

  return {
    state: {
      transcriptText,
      sentencesWithTime,
      activeSentenceIndex,
      isAiRestructuring,
      isTranscribing,
      contentBlocks,
      lastSaveTime,
      saveStatus,
      saveError,
      isPptMatching,
      pptMatchMessage,
      pendingAiText,
      loadedNote,
      isLoaded,
      hasLocalChanges,
      partialText,
      streamingFinals,
      editorFocused,
    },
    actions: {
      setTranscriptText,
      updateTranscriptText,
      receiveAiText,
      appendTranscriptText,
      upsertStreamingTranscriptChunk,
      clearStreamingTranscriptChunks,
      setIsAiRestructuring,
      setIsTranscribing,
      setContentBlocks,
      updateContentBlocks,
      updateContentBlockDraft,
      commitContentBlockDraft,
      setActiveSentenceIndex,
      saveContent,
      parseSentencesWithTime,
      setSentencesWithTime,
      clearDerivedTranscriptViews,
      clearContentBlocks,
      receivePartial,
      receiveFinal,
      clearStreamingState,
      clearPartialText,
      updateTranscriptDraft,
      commitTranscriptDraft,
      setEditorFocused,
      setGetCurrentNotes,
      scheduleSave,
      markUserEdited: () => markLocalChanged(true),
      markLocalChanged: () => markLocalChanged(false),
      applyPendingAiText: () => {
        if (!pendingAiText) return;
        userEditedRef.current = false;
        setTranscriptText(pendingAiText);
        setPendingAiText(null);
        setSentencesWithTime([]);
        setActiveSentenceIndex(null);
        markLocalChanged(false);
      },
      dismissPendingAiText: () => setPendingAiText(null),
    },
  };
}
