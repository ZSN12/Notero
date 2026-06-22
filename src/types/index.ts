export interface Notebook {
  id: string;
  title: string;
  description: string;
  icon: string;
  color: string;
  sessionCount: number;
  updatedAt: string;
  createdAt: string;
}

export interface Session {
  id: string;
  notebookId: string;
  title: string;
  summary: string;
  keywords: string[];
  icon: string;
  date: string;
  duration: string;
  content: string;
}

export interface Note {
  id: string;
  sessionId: string;
  title: string;
  content: string;
  createdAt: string;
  updatedAt: string;
}

export type DialogType = 'notebook' | 'session' | null;

export interface DialogState {
  isOpen: boolean;
  type: DialogType;
  notebookId?: string;
  editingNotebook?: Notebook;
  editingSession?: Session;
}

export interface SessionNoteBundle {
  title: string;
  summary?: string;
  keywords?: string[];
  content?: string;
  transcript?: unknown[];
  ppt_images?: unknown[];
  layout_blocks?: import('@/lib/noteLayout').NoteLayoutBlock[];
}

export interface NotebookPackage {
  format_version: number;
  notebook: {
    title: string;
    description?: string;
    icon?: string;
    color?: string;
  };
  sessions: SessionNoteBundle[];
}
