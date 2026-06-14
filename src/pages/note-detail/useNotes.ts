import { useState, useCallback, useRef } from 'react';

export interface StudentNote {
  type: string;
  content: string;
}

export function useNotes() {
  const [notes, setNotes] = useState<StudentNote[]>([{ type: 'text', content: '' }]);
  const [editingNote, setEditingNote] = useState<string | null>(null);
  const notesDraftRef = useRef<StudentNote[]>([{ type: 'text', content: '' }]);

  const cleanNoteContent = useCallback((value: string) => {
    const trimmed = value.trim();
    if (!trimmed || /^[-\s]+$/.test(trimmed)) return '';
    return trimmed;
  }, []);

  const updateNote = useCallback((index: number, content: string) => {
    setNotes((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], content };
      notesDraftRef.current = updated.map((n) => ({ ...n }));
      return updated;
    });
  }, []);

  const updateNoteDraft = useCallback((index: number, content: string) => {
    const draft = notesDraftRef.current;
    if (draft[index]) {
      draft[index] = { ...draft[index], content };
    }
  }, []);

  const commitNotesDraft = useCallback(() => {
    setNotes(notesDraftRef.current.map((n) => ({ ...n })));
  }, []);

  const resetDrafts = useCallback((newNotes: StudentNote[]) => {
    const next = newNotes.length > 0 ? newNotes.map((n) => ({ ...n })) : [{ type: 'text', content: '' }];
    notesDraftRef.current = next;
    setNotes(next);
  }, []);

  const parseNotesFromContent = useCallback((content: string, hasTranscript: boolean = false) => {
    const transcriptSectionMatch = content.match(/^## 语音转文字\n\n([\s\S]*?)\n\n---\n\n([\s\S]*)$/);
    if (transcriptSectionMatch && transcriptSectionMatch[2].trim()) {
      return [{ type: 'text', content: cleanNoteContent(transcriptSectionMatch[2]) }];
    }
    // Only treat raw content as notes when there's genuinely no transcript.
    // If transcript exists, raw content is old-format data (transcript saved
    // directly to content without the ## header) and should be ignored.
    if (!hasTranscript && !content.startsWith('## 语音转文字\n\n') && content.trim()) {
      return [{ type: 'text', content: cleanNoteContent(content) }];
    }
    return [{ type: 'text', content: '' }];
  }, [cleanNoteContent]);

  return {
    state: {
      notes,
      editingNote,
    },
    refs: {
      notesDraftRef,
    },
    actions: {
      setNotes,
      setEditingNote,
      updateNote,
      updateNoteDraft,
      commitNotesDraft,
      resetDrafts,
      parseNotesFromContent,
    },
  };
}
