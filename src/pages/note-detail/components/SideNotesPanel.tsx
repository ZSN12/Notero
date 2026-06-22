import { Edit3 } from 'lucide-react';
import type { RichTextEditorHandle } from '@/components/RichTextEditor';
import RichTextEditor from '@/components/RichTextEditor';
import type { useNotes } from '@/pages/note-detail/useNotes';
import type { useTranscript } from '@/pages/note-detail/useTranscript';

interface SideNotesPanelProps {
  noteEditRef: React.RefObject<RichTextEditorHandle>;
  notesHook: ReturnType<typeof useNotes>;
  transcript: ReturnType<typeof useTranscript>;
  activeTextElRef: React.MutableRefObject<HTMLDivElement | null>;
}

export function SideNotesPanel({ noteEditRef, notesHook, transcript, activeTextElRef }: SideNotesPanelProps) {
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="flex-shrink-0 px-3 py-2 border-b border-slate-100 dark:border-slate-700/50 flex items-center gap-1.5">
        <Edit3 className="w-3.5 h-3.5 text-amber-500" />
        <h3 className="text-xs font-semibold text-slate-600 dark:text-slate-300">随堂思考与重难点</h3>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        <RichTextEditor
          ref={noteEditRef}
          value={notesHook.state.notes.length > 0 ? notesHook.state.notes[0].content : ''}
          onChange={(text) => {
            transcript.actions.markUserEdited();
            notesHook.actions.updateNoteDraft(0, text);
            transcript.actions.scheduleSave(() => notesHook.refs.notesDraftRef.current, 300);
          }}
          onFocus={() => {
            activeTextElRef.current = noteEditRef.current?.getRootElement() ?? null;
          }}
          onBlur={() => {
            notesHook.actions.commitNotesDraft();
            transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, false);
          }}
          placeholder="在此记录随堂思考与重难点..."
          className="rich-text-editor w-full p-2.5 text-sm text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-200 leading-relaxed"
        />
      </div>
    </div>
  );
}
