import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import CreateDialog from '@/components/CreateDialog'
import * as store from '@/store/useStore'

const mockSession = {
  id: 's-1',
  notebookId: 'nb-1',
  title: 'Old Session Title',
  keywords: [],
  icon: 'FileText',
  date: '2026-06-01',
  duration: '30min',
  content: '',
}

const mockNotebook = {
  id: 'nb-1',
  title: 'Old Notebook Title',
  description: '',
  icon: 'BookOpen',
  color: 'from-blue-500 to-blue-600',
  sessionCount: 1,
  updatedAt: '2026-06-01',
  createdAt: '2026-06-01',
}

vi.mock('@/store/useStore', () => ({
  useStore: vi.fn((selector?) => {
    const state = {
      notebooks: [],
      sessions: [],
      dialog: { isOpen: true, type: 'session' as const, notebookId: 'nb-1', editingSession: mockSession },
      loading: false,
      error: null,
      openDialog: vi.fn(),
      closeDialog: vi.fn(),
      loadNotebooks: vi.fn(),
      loadSessions: vi.fn(),
      createNotebook: vi.fn(),
      updateNotebook: vi.fn(),
      createSession: vi.fn(),
      updateSession: vi.fn(),
      removeNotebook: vi.fn(),
      removeSession: vi.fn(),
    }
    return selector ? selector(state) : state
  }),
}))

describe('CreateDialog session edit mode', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('initializes input with existing session title', () => {
    render(<CreateDialog />)
    expect(screen.getByDisplayValue('Old Session Title')).toBeInTheDocument()
    expect(screen.getByText('编辑课次名称')).toBeInTheDocument()
  })

  it('calls updateSession with new title on submit', async () => {
    const updateSessionMock = vi.fn().mockResolvedValue(undefined)
    const closeDialogMock = vi.fn()
    vi.mocked(store.useStore).mockImplementation((selector?) => {
      const state = {
        notebooks: [],
        sessions: [],
        dialog: { isOpen: true, type: 'session' as const, notebookId: 'nb-1', editingSession: mockSession },
        loading: false,
        error: null,
        openDialog: vi.fn(),
        closeDialog: closeDialogMock,
        loadNotebooks: vi.fn(),
        loadSessions: vi.fn(),
        createNotebook: vi.fn(),
        updateNotebook: vi.fn(),
        createSession: vi.fn(),
        updateSession: updateSessionMock,
        removeNotebook: vi.fn(),
        removeSession: vi.fn(),
      }
      return selector ? selector(state) : state
    })

    render(<CreateDialog />)
    const input = screen.getByDisplayValue('Old Session Title')
    fireEvent.change(input, { target: { value: 'New Session Title' } })
    fireEvent.click(screen.getByText('更新'))

    await waitFor(() => {
      expect(updateSessionMock).toHaveBeenCalledWith('s-1', 'New Session Title')
    })
    expect(closeDialogMock).toHaveBeenCalled()
  })

  it('calls updateNotebook with new title in notebook edit mode', async () => {
    const updateNotebookMock = vi.fn().mockResolvedValue(undefined)
    const closeDialogMock = vi.fn()
    vi.mocked(store.useStore).mockImplementation((selector?) => {
      const state = {
        notebooks: [],
        sessions: [],
        dialog: { isOpen: true, type: 'notebook' as const, editingNotebook: mockNotebook },
        loading: false,
        error: null,
        openDialog: vi.fn(),
        closeDialog: closeDialogMock,
        loadNotebooks: vi.fn(),
        loadSessions: vi.fn(),
        createNotebook: vi.fn(),
        updateNotebook: updateNotebookMock,
        createSession: vi.fn(),
        updateSession: vi.fn(),
        removeNotebook: vi.fn(),
        removeSession: vi.fn(),
      }
      return selector ? selector(state) : state
    })

    render(<CreateDialog />)
    const input = screen.getByDisplayValue('Old Notebook Title')
    fireEvent.change(input, { target: { value: 'New Notebook Title' } })
    fireEvent.click(screen.getByText('更新'))

    await waitFor(() => {
      expect(updateNotebookMock).toHaveBeenCalledWith('nb-1', 'New Notebook Title')
    })
  })
})
