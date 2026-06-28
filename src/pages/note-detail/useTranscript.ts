import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { fetchNote, updateNote as apiUpdateNote, insertPPTIntoTranscript, ContentBlock, Slide } from '@/services/api';
import type { BackendNote, ParagraphTimeRange, TranscriptChunk } from '@/services/api';
import { contentBlocksFromLayout, layoutFromNoteParts, normalizeHtmlText, transcriptTextFromRawTranscript } from '@/lib/noteLayout';
import { getErrorMessage } from '@/lib/error';

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
  startIdx?: number;
  endIdx?: number;
}

export function computeParagraphTimeRanges(
  transcriptText: string,
  sentencesWithTime: SentenceWithTime[],
): ParagraphTimeRange[] {
  if (!transcriptText.trim() || sentencesWithTime.length === 0) return [];

  const paragraphs = transcriptText
    .split('\n\n')
    .map((p) => p.trim())
    .filter(Boolean);

  // Assign each sentence to the first paragraph whose text contains the sentence.
  // This is robust to AI restructure because it matches by content rather than
  // relying on fragile character indices after the text has been edited.
  const assigned: Map<number, SentenceWithTime[]> = new Map();
  paragraphs.forEach((_, i) => assigned.set(i, []));

  for (const sentence of sentencesWithTime) {
    const sentenceText = sentence.text.trim();
    if (!sentenceText) continue;
    for (let i = 0; i < paragraphs.length; i++) {
      if (paragraphs[i].includes(sentenceText)) {
        assigned.get(i)!.push(sentence);
        break;
      }
    }
  }

  return paragraphs
    .map((para, i) => {
      const sentencesInPara = assigned.get(i) || [];
      if (sentencesInPara.length === 0) return null;
      return {
        text: para,
        start_ms: Math.min(...sentencesInPara.map((s) => Math.round(s.startTime * 1000))),
        end_ms: Math.max(...sentencesInPara.map((s) => Math.round(s.endTime * 1000))),
      };
    })
    .filter((range): range is ParagraphTimeRange => range !== null);
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
  const [loadedNote, setLoadedNote] = useState<BackendNote | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const [hasLocalChanges, setHasLocalChanges] = useState(false);
  const [partialText, setPartialText] = useState('');
  const [streamingFinals, setStreamingFinals] = useState<string[]>([]);
  const prevTranscriptRef = useRef('');
  const userEditedRef = useRef(false);
  const hasLocalChangesRef = useRef(false);
  const transcriptTextRef = useRef('');
  const contentBlocksRef = useRef<ContentBlock[]>([]);
  const streamChunksRef = useRef<Map<string, string>>(new Map());
  const getCurrentNotesRef = useRef<() => StudentNote[]>(() => []);
  const scheduleSaveTimerRef = useRef<number | null>(null);

  const markLocalChanged = useCallback((isUserEdit = true) => {
    if (isUserEdit) userEditedRef.current = true;
    hasLocalChangesRef.current = true;
    setHasLocalChanges(true);
    setSaveStatus('idle');
  }, []);

  const markBackendSynced = useCallback(() => {
    hasLocalChangesRef.current = false;
    setHasLocalChanges(false);
    setSaveStatus('saved');
    setSaveError(null);
    setLastSaveTime(Date.now());
  }, []);

  useEffect(() => {
    transcriptTextRef.current = transcriptText;
  }, [transcriptText]);

  useEffect(() => {
    contentBlocksRef.current = contentBlocks;
  }, [contentBlocks]);

  const normalizeEditableHtml = useCallback((s: string) => normalizeHtmlText(s), []);

  const dedupeKey = useCallback((value: string) => {
    return normalizeEditableHtml(value)
      .toLowerCase()
      // eslint-disable-next-line no-useless-escape
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
    const blockText = transcriptFromBlocks(contentBlocksRef.current);
    return cleanTranscriptText(blockText || transcriptTextRef.current);
  }, [cleanTranscriptText, transcriptFromBlocks]);

  const syncContentBlocksFromTranscript = useCallback((value: string) => {
    const paragraphs = cleanTranscriptText(value)
      .split(/\n{2,}/)
      .map((part) => normalizeEditableHtml(part))
      .filter(Boolean);
    const textBlocks: ContentBlock[] = paragraphs.map((content) => ({ type: 'text', content }));
    const currentBlocks = contentBlocksRef.current;
    const imageBlocks = currentBlocks.filter((block) => block.type === 'image');

    if (imageBlocks.length === 0) {
      contentBlocksRef.current = textBlocks;
      setContentBlocks(textBlocks);
      return;
    }

    const oldTextCount = currentBlocks.filter((block) => block.type === 'text').length;
    const mergedBlocks = [...textBlocks];
    for (const imageBlock of imageBlocks) {
      const originalIndex = currentBlocks.findIndex((block) => block === imageBlock);
      const precedingText = currentBlocks
        .slice(0, originalIndex >= 0 ? originalIndex : 0)
        .filter((block) => block.type === 'text').length;
      const ratio = oldTextCount > 0 ? precedingText / oldTextCount : 1;
      const target = Math.min(mergedBlocks.length, Math.round(ratio * mergedBlocks.length));
      mergedBlocks.splice(target, 0, imageBlock);
    }
    contentBlocksRef.current = mergedBlocks;
    setContentBlocks(mergedBlocks);
  }, [cleanTranscriptText, normalizeEditableHtml]);

  const updateTranscriptText = useCallback((value: string, markUserEdit = true) => {
    if (markUserEdit) markLocalChanged(true);
    else setSaveStatus('idle');
    transcriptTextRef.current = value;
    syncContentBlocksFromTranscript(value);
    setTranscriptText(value);
  }, [markLocalChanged, syncContentBlocksFromTranscript]);

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
    const nextText = dedupedParts.join('\n\n');
    transcriptTextRef.current = nextText;
    setTranscriptText(nextText);
  }, [isRepeatedText, markLocalChanged]);

  const updateContentBlocks = useCallback((blocks: ContentBlock[], markUserEdit = true, markLocalChange = markUserEdit) => {
    if (markLocalChange) markLocalChanged(markUserEdit);
    else setSaveStatus('idle');
    contentBlocksRef.current = blocks;
    setContentBlocks(blocks);
  }, [markLocalChanged]);

  const clearDerivedTranscriptViews = useCallback((keepPptBlocks = false) => {
    setSentencesWithTime([]);
    setActiveSentenceIndex(null);
    if (!keepPptBlocks) {
      contentBlocksRef.current = [];
      setContentBlocks([]);
    }
  }, []);

  const clearContentBlocks = useCallback(() => {
    contentBlocksRef.current = [];
    setContentBlocks([]);
  }, []);

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

  const buildBlocksWithPreservedImages = useCallback((
    textBlocks: ContentBlock[],
    imageBlocks: ContentBlock[],
    originalBlocks: ContentBlock[],
  ): ContentBlock[] => {
    if (imageBlocks.length === 0) return textBlocks;
    const oldTextCount = originalBlocks.filter(block => block.type === 'text').length;
    const result = [...textBlocks];
    for (const imageBlock of imageBlocks) {
      const originalIndex = originalBlocks.findIndex(block => block === imageBlock);
      const precedingText = originalBlocks
        .slice(0, originalIndex >= 0 ? originalIndex : 0)
        .filter(block => block.type === 'text').length;
      const ratio = oldTextCount > 0 ? precedingText / oldTextCount : 1;
      const target = Math.min(result.length, Math.round(ratio * textBlocks.length));
      result.splice(target, 0, imageBlock);
    }
    return result;
  }, []);

  const replaceTranscriptBlocks = useCallback((value: string) => {
    const paragraphs = value.split(/\n{2,}/).map(part => part.trim()).filter(Boolean);
    setContentBlocks(prev => {
      const oldTextCount = prev.filter(block => block.type === 'text').length;
      const images = prev
        .map((block, index) => ({ block, index }))
        .filter(item => item.block.type === 'image');

      const textBlocks: ContentBlock[] = paragraphs.map(content => ({ type: 'text', content }));
      if (images.length === 0) {
        // No images: still create text blocks so the editor has content to render.
        return textBlocks;
      }

      const result = [...textBlocks];
      for (const { block, index } of images) {
        const precedingText = prev.slice(0, index).filter(item => item.type === 'text').length;
        const ratio = oldTextCount > 0 ? precedingText / oldTextCount : 1;
        const target = Math.min(result.length, Math.round(ratio * textBlocks.length));
        result.splice(target, 0, block);
      }
      return result;
    });
  }, []);

  const receiveAiText = useCallback((value: string, options?: { force?: boolean; authoritative?: boolean }) => {
    const nextText = value.trim();
    if (!nextText) return;
    // Only an explicit force may overwrite a user edit in progress.
    // Authoritative backend text bypasses the 85% length gate but still
    // respects user edit protection so the user can choose to apply or keep.
    if (userEditedRef.current && !options?.force) {
      setPendingAiText(nextText);
      return;
    }
    if (options?.force || options?.authoritative) {
      userEditedRef.current = false;
      setTranscriptText(nextText);
      replaceTranscriptBlocks(nextText);
      setSentencesWithTime([]);
      setActiveSentenceIndex(null);
      markBackendSynced();
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
        markBackendSynced();
        return nextText;
      }
      // If lengths are close (within ±15%), it's a correction — accept.
      // If DB is longer, it's a restructure — accept.
      // If DB is significantly shorter, reject (stale snapshot).
      if (nextText.length >= prevTrimmed.length * 0.85) {
        // Replace UI text but keep PPT image blocks alive
        clearDerivedTranscriptViews(true);
        markBackendSynced();
        return nextText;
      }
      // DB text is much shorter — stale snapshot, keep live UI text
      return prev;
    });
  }, [clearDerivedTranscriptViews, markBackendSynced, replaceTranscriptBlocks]);

  const parseSentencesWithTime = useCallback((note: BackendNote): SentenceWithTime[] => {
    if (!note?.transcript || !Array.isArray(note.transcript) || note.transcript.length === 0) return [];

    const transcriptSourceText = (chunk: TranscriptChunk) => chunk.raw_text || chunk.text || '';
    const sortedChunks = note.transcript
      .sort((a, b) => (a.chunk_index || 0) - (b.chunk_index || 0))
      .filter((chunk) => transcriptSourceText(chunk).trim());

    if (sortedChunks.length === 0) return [];

    const fullText = sortedChunks.map(transcriptSourceText).join(' ').trim();

    // Build timestamp array with sequential position tracking to correctly handle
    // duplicate words (e.g. "的", "是", "在" appear many times in Chinese text).
    // Using indexOf(word, searchPos) ensures each occurrence maps to its actual position.
    // Backend timestamps are in milliseconds; convert to seconds for audio API compatibility.
    const allTimestamps: { text: string; start: number; end: number; pos: number }[] = [];
    let searchPos = 0;
    for (const chunk of sortedChunks) {
      if (chunk.timestamps && Array.isArray(chunk.timestamps)) {
        for (const ts of chunk.timestamps) {
          const word = (ts.text || '').trim();
          if (!word) continue;
          const pos = fullText.indexOf(word, searchPos);
          if (pos !== -1) {
            const startMs = (ts.start_ms ?? ts.start ?? 0) as number;
            const endMs = (ts.end_ms ?? ts.end ?? 0) as number;
            allTimestamps.push({ text: word, start: startMs / 1000, end: endMs / 1000, pos });
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
          startIdx: sentence.startIdx,
          endIdx: sentence.endIdx,
        });
      } else if (result.length > 0) {
        // Fallback: estimate time range from previous sentence
        const prev = result[result.length - 1];
        result.push({
          text: sentence.text,
          startTime: prev.endTime,
          endTime: prev.endTime + 2,
          startIdx: sentence.startIdx,
          endIdx: sentence.endIdx,
        });
      } else {
        // First sentence(s) have no timestamp match — use the first available timestamp
        result.push({
          text: sentence.text,
          startTime: allTimestamps[0]?.start ?? 0,
          endTime: (allTimestamps[0]?.start ?? 0) + 2,
          startIdx: sentence.startIdx,
          endIdx: sentence.endIdx,
        });
      }
    }

    return result;
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
        // Final/user-edited transcript entries are authoritative. note.content
        // can lag behind after an async AI finalization and must not override it.
        let transcriptRestored = false;
        let restoredTranscriptText = '';
        const backendTranscript = transcriptTextFromRawTranscript(note.transcript);
        const hasFinalTranscript = note.transcript?.some?.(
          (chunk) => chunk.correction_stage === 'final' || chunk.correction_stage === 'user_edited',
        );
        if (hasFinalTranscript) {
          // An explicitly empty user_edited display_text is a valid deletion and
          // must not fall back to raw_text or older content.
          restoredTranscriptText = cleanTranscriptText(backendTranscript);
          setTranscriptText(restoredTranscriptText);
          transcriptRestored = true;
        } else if (typeof note.content === 'string' && note.content.startsWith('## 语音转文字\n\n')) {
          const match = note.content.match(/^## 语音转文字\n\n([\s\S]*?)(?:\n\n---\n\n[\s\S]*)?$/);
          restoredTranscriptText = match ? cleanTranscriptText(match[1] || '') : '';
          setTranscriptText(restoredTranscriptText);
          transcriptRestored = true;
        } else if (note.content) {
          // Fallback: content exists but doesn't match expected format
          restoredTranscriptText = cleanTranscriptText(note.content);
          if (restoredTranscriptText) {
            setTranscriptText(restoredTranscriptText);
            transcriptRestored = true;
          }
        }
        if (!transcriptRestored && note.transcript && Array.isArray(note.transcript) && note.transcript.length > 0) {
          const fullTranscript = backendTranscript;
          if (fullTranscript) {
            restoredTranscriptText = cleanTranscriptText(fullTranscript);
            setTranscriptText(restoredTranscriptText);
          }
        }
        // Parse sentence-time mapping from transcript JSON (always needs note.transcript)
        if (note.transcript && Array.isArray(note.transcript) && note.transcript.length > 0) {
          const parsed = parseSentencesWithTime(note);
          if (parsed.length > 0) setSentencesWithTime(parsed);
        }
        const restoredBlocks = contentBlocksFromLayout(note.layout_blocks);
        if (transcriptRestored) {
          // Authoritative transcript (final/user_edited) is the source of truth.
          // Rebuild blocks from it, preserving any PPT images from saved layout_blocks.
          const imageBlocks = restoredBlocks.filter(block => block.type === 'image');
          const textBlocks: ContentBlock[] = restoredTranscriptText
            .split(/\n{2,}/)
            .map(part => part.trim())
            .filter(Boolean)
            .map(content => ({ type: 'text', content }));
          const mergedBlocks = imageBlocks.length > 0
            ? buildBlocksWithPreservedImages(textBlocks, imageBlocks, restoredBlocks)
            : textBlocks;
          if (mergedBlocks.length > 0) {
            updateContentBlocks(mergedBlocks, false, false);
          }
        } else if (restoredBlocks.length > 0) {
          updateContentBlocks(restoredBlocks, false);
          const layoutText = transcriptFromBlocks(restoredBlocks);
          // Only override transcriptText from layout_blocks if we haven't already
          // restored a final transcript, and the layout text is actually newer/non-empty.
          if (layoutText) {
            setTranscriptText(cleanTranscriptText(layoutText));
          }
        } else if (note.ppt_images && note.ppt_images.length > 0) {
          setTimeout(async () => {
            try {
              const blocks = await insertPPTIntoTranscript(sessionId);
              if (blocks.blocks?.some((b: ContentBlock) => b.type === 'image')) {
                updateContentBlocks(blocks.blocks, false, false);
              }
            } catch (err) {
              console.error('[useTranscript] Failed to auto-insert PPT during history load:', err);
            }
          }, 500);
        }
      }
    } catch (error) {
      // Missing note is a normal empty-state, not a load failure.
      const message = getErrorMessage(error);
      const isMissingNote =
        message.includes('404') ||
        message.includes('Not found') ||
        message.includes('Note not found');
      if (!isMissingNote) {
        console.error('Failed to load history:', error);
      }
    }
    finally {
      hasLocalChangesRef.current = false;
      setHasLocalChanges(false);
      setIsLoaded(true);
    }
  }, [cleanTranscriptText, sessionId, parseSentencesWithTime, transcriptFromBlocks, updateContentBlocks, buildBlocksWithPreservedImages]);

  useEffect(() => { loadHistory(); }, [loadHistory]);

  const saveContent = useCallback(async (currentNotes: StudentNote[], forceRetry = false) => {
    if (!sessionId) return false;
    if (!forceRetry && !hasLocalChangesRef.current) return true;
    const cleanTranscript = cleanTranscriptText(getCurrentTranscript());
    const notesContent = currentNotes.map(n => normalizeEditableHtml(n.content)).filter(Boolean).join('\n\n');

    // Always keep the transcript marker so we can distinguish "user saved an empty
    // transcript" from "content was never set" when the note is reloaded.
    const fullContent = `## 语音转文字\n\n${cleanTranscript}\n\n---\n\n${notesContent}`.trim();
    const layoutBlocks = layoutFromNoteParts(cleanTranscript, contentBlocksRef.current, currentNotes);
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
      } catch (error) {
        console.error('[NoteDetail] Failed to save content:', error);
        setSaveStatus('error');
        setSaveError(getErrorMessage(error) || '保存失败，请检查网络后重试');
        return false;
      }
    }
    hasLocalChangesRef.current = false;
    setHasLocalChanges(false);
    return true;
  }, [cleanTranscriptText, getCurrentTranscript, normalizeEditableHtml, sessionId]);

  const setGetCurrentNotes = useCallback((fn: () => StudentNote[]) => {
    getCurrentNotesRef.current = fn;
  }, []);

  const scheduleSave = useCallback((getNotes: () => StudentNote[], delay = 300) => {
    if (scheduleSaveTimerRef.current) window.clearTimeout(scheduleSaveTimerRef.current);
    scheduleSaveTimerRef.current = window.setTimeout(() => {
      scheduleSaveTimerRef.current = null;
      saveContent(getNotes(), false);
    }, delay);
  }, [saveContent]);

  const updateTranscriptDraft = useCallback((text: string) => {
    updateTranscriptText(text, true);
  }, [updateTranscriptText]);

  const commitTranscriptDraft = useCallback(() => {
    // transcript text is already live
  }, []);

  const clearPartialText = useCallback(() => {
    setPartialText('');
  }, []);

  const setEditorFocused = useCallback((_focused: boolean) => {
    // placeholder for future focus tracking
  }, []);

  const updateContentBlockDraft = useCallback((index: number, content: string) => {
    const base = contentBlocksRef.current;
    const updated = [...base];
    if (updated[index]) updated[index] = { ...updated[index], content };
    contentBlocksRef.current = updated;
    setContentBlocks((prev) => {
      const next = [...prev];
      if (next[index]) next[index] = { ...next[index], content };
      return next;
    });
    markLocalChanged(true);
  }, [markLocalChanged]);

  const commitContentBlockDraft = useCallback(() => {
    // blocks are already live
  }, []);

  useEffect(() => {
    return () => {
      if (scheduleSaveTimerRef.current) {
        window.clearTimeout(scheduleSaveTimerRef.current);
        scheduleSaveTimerRef.current = null;
      }
      if (hasLocalChangesRef.current) {
        void saveContent(getCurrentNotesRef.current(), false);
      }
    };
  }, [saveContent]);

  useEffect(() => {
    if (!isRecording || !sessionId) return;
    const interval = setInterval(async () => {
      try {
        const note = await fetchNote(sessionId);
        if (note?.transcript && Array.isArray(note.transcript) && note.transcript.length > 0) {
          const corrected = transcriptTextFromRawTranscript(note.transcript);
          if (corrected.trim() && corrected.trim() !== transcriptText.trim()) {
            receiveAiText(corrected);
            setIsAiRestructuring(false);
            // Re-parse sentence-time mapping: AI restructured text changed,
            // old sentence boundaries no longer match
            const parsed = parseSentencesWithTime(note);
            if (parsed.length > 0) setSentencesWithTime(parsed);
          }
        }
      } catch (err) {
        console.error('[useTranscript] Correction poll failed:', err);
      }
    }, CORRECTION_POLL_MS);
    return () => clearInterval(interval);
  }, [isRecording, sessionId, transcriptText, parseSentencesWithTime, receiveAiText]);

  useEffect(() => {
    if (!isRecording && sessionId && transcriptText) {
      prevTranscriptRef.current = transcriptText;
      setIsTranscribing(true);
    }
    // Intentionally capture transcriptText only when recording stops, not on every text change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
        if (!note) return;
        const corrected = transcriptTextFromRawTranscript(note.transcript);
        const hasFinalTranscript = note.transcript?.some?.(
          (chunk) => chunk.correction_stage === 'final',
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
      } catch (err) {
        console.error('[useTranscript] Final transcript poll failed:', err);
      }

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
  }, [isTranscribing, isRecording, sessionId, parseSentencesWithTime, receiveAiText]);

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
        const currentNotes = getCurrentNotesRef.current();
        const notesContent = currentNotes.map(n => normalizeEditableHtml(n.content)).filter(Boolean).join('\n\n');
        const content = `## 语音转文字\n\n${cleanTranscript}\n\n---\n\n${notesContent}`.trim();
        const layoutBlocks = layoutFromNoteParts(cleanTranscript, contentBlocksRef.current, currentNotes);
        const payload = JSON.stringify({ content, layout_blocks: layoutBlocks });
        try {
          const xhr = new XMLHttpRequest();
          xhr.open('PUT', `/api/notes/session/${sessionId}`, false);
          xhr.setRequestHeader('Content-Type', 'application/json');
          if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`);
          xhr.send(payload);
        } catch (err) {
          console.error('[useTranscript] Beforeunload auto-save failed:', err);
        }
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [sessionId, cleanTranscriptText, getCurrentTranscript, normalizeEditableHtml]);

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
  }, [isRecording, sessionId, slides.length, updateContentBlocks]);

  useEffect(() => {
    if (isRecording && slides.length > 0) {
      const t = setTimeout(() => setIsAiRestructuring(true), PPT_INSERT_INITIAL_MS);
      return () => clearTimeout(t);
    } else {
      setIsAiRestructuring(false);
    }
  }, [isRecording, slides.length]);

  const paragraphTimeRanges = useMemo(
    () => computeParagraphTimeRanges(transcriptText, sentencesWithTime),
    [transcriptText, sentencesWithTime],
  );

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
      paragraphTimeRanges,
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
      setActiveSentenceIndex,
      saveContent,
      parseSentencesWithTime,
      setSentencesWithTime,
      clearDerivedTranscriptViews,
      clearContentBlocks,
      receivePartial,
      receiveFinal,
      clearStreamingState,
      getCurrentTranscript,
      setGetCurrentNotes,
      scheduleSave,
      updateTranscriptDraft,
      commitTranscriptDraft,
      clearPartialText,
      setEditorFocused,
      updateContentBlockDraft,
      commitContentBlockDraft,
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
