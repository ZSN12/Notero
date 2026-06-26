import { useState, useCallback, useRef, useEffect } from 'react';

export interface StudentNote {
  type: string;
  content: string;
}

export function useNotes() {
  const [notes, setNotes] = useState<StudentNote[]>([{ type: 'text', content: '' }]);
  const [editingNote, setEditingNote] = useState<string | null>(null);
  const notesDraftRef = useRef<StudentNote[]>(notes);

  useEffect(() => {
    notesDraftRef.current = notes;
  }, [notes]);

  const cleanNoteContent = useCallback((value: string) => {
    const trimmed = value.trim();
    if (!trimmed || /^[-\s]+$/.test(trimmed)) return '';
    return trimmed;
  }, []);

  const updateNote = useCallback((index: number, content: string) => {
    setNotes((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], content };
      notesDraftRef.current = updated;
      return updated;
    });
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

  const resetDrafts = useCallback((nextNotes?: StudentNote[]) => {
    const reset = nextNotes && nextNotes.length > 0 ? nextNotes : [{ type: 'text', content: '' }];
    notesDraftRef.current = reset;
    setNotes(reset);
  }, []);

  const updateNoteDraft = useCallback((index: number, content: string) => {
    updateNote(index, content);
  }, [updateNote]);

  const commitNotesDraft = useCallback(() => {
    setNotes(() => {
      const committed = notesDraftRef.current.map((n) => ({ ...n, content: n.content }));
      return committed;
    });
  }, []);

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
      parseNotesFromContent,
      resetDrafts,
      updateNoteDraft,
      commitNotesDraft,
    },
  };
}
