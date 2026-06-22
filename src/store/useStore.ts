import { create } from 'zustand';
import type { Notebook, Session, DialogState, DialogType } from '@/types';
import {
  fetchNotebooks,
  createNotebook as apiCreateNotebook,
  updateNotebook as apiUpdateNotebook,
  deleteNotebook as apiDeleteNotebook,
  fetchSessions,
  createSession as apiCreateSession,
  deleteSession as apiDeleteSession,
} from '@/services/api';

interface StoreState {
  notebooks: Notebook[];
  sessions: Session[];
  dialog: DialogState;
  loading: boolean;
  error: string | null;
  openDialog: (type: DialogType, notebookId?: string, editingNotebook?: Notebook) => void;
  closeDialog: () => void;
  loadNotebooks: () => Promise<void>;
  loadSessions: (notebookId: string) => Promise<void>;
  createNotebook: (title: string) => Promise<void>;
  updateNotebook: (notebookId: string, title: string) => Promise<void>;
  createSession: (notebookId: string, title: string) => Promise<void>;
  removeNotebook: (notebookId: string) => Promise<void>;
  removeSession: (notebookId: string, sessionId: string) => Promise<void>;
}

export const useStore = create<StoreState>((set, get) => ({
  notebooks: [],
  sessions: [],
  dialog: { isOpen: false, type: null },
  loading: false,
  error: null,

  openDialog: (type, notebookId, editingNotebook) =>
    set({ dialog: { isOpen: true, type, notebookId, editingNotebook } }),
  closeDialog: () => set({ dialog: { isOpen: false, type: null } }),

  loadNotebooks: async () => {
    try {
      set({ loading: true, error: null });
      const notebooks = await fetchNotebooks();
      set({ notebooks, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : '加载失败',
        loading: false,
      });
    }
  },

  loadSessions: async (notebookId) => {
    try {
      set({ loading: true, error: null });
      const sessions = await fetchSessions(notebookId);
      set({ sessions, loading: false });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : '加载失败',
        loading: false,
      });
    }
  },

  createNotebook: async (title) => {
    try {
      const notebook = await apiCreateNotebook(title);
      set((state) => ({
        notebooks: [...state.notebooks, notebook],
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : '创建失败',
      });
      throw error;
    }
  },

  updateNotebook: async (notebookId, title) => {
    try {
      const updated = await apiUpdateNotebook(notebookId, title);
      set((state) => ({
        notebooks: state.notebooks.map((n) =>
          n.id === notebookId ? updated : n
        ),
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : '更新失败',
      });
      throw error;
    }
  },

  createSession: async (notebookId, title) => {
    try {
      const session = await apiCreateSession(notebookId, title);
      set((state) => {
        const notebook = state.notebooks.find((n) => n.id === notebookId);
        return {
          sessions: [...state.sessions, session],
          notebooks: notebook
            ? state.notebooks.map((n) =>
                n.id === notebookId
                  ? { ...n, sessionCount: n.sessionCount + 1 }
                  : n
              )
            : state.notebooks,
        };
      });
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : '创建失败',
      });
      throw error;
    }
  },

  removeNotebook: async (notebookId) => {
    try {
      await apiDeleteNotebook(notebookId);
      set((state) => ({
        notebooks: state.notebooks.filter((n) => n.id !== notebookId),
        sessions: state.sessions.filter((s) => s.notebookId !== notebookId),
      }));
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : '删除失败',
      });
      throw error;
    }
  },

  removeSession: async (notebookId, sessionId) => {
    try {
      await apiDeleteSession(sessionId);
    } catch (error) {
      set({
        error: error instanceof Error ? error.message : '删除失败',
      });
      throw error;
    }

    // The session is already deleted on the server; remove it locally even if
    // the subsequent list refresh fails.
    set((state) => ({
      sessions: state.sessions.filter((s) => s.id !== sessionId),
    }));

    // Reload sessions from backend to ensure sessionCount is accurate.
    // loadSessions swallows its own errors to keep page loads stable, so we
    // detect failure by checking the store error state.
    await get().loadSessions(notebookId);
    if (get().error) {
      set({ error: '列表刷新失败' });
      throw new Error('列表刷新失败');
    }
  },
}));
