import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import NotebookCard from '@/components/NotebookCard'
import * as store from '@/store/useStore'

const mockNotebook = {
  id: 'nb-1',
  title: 'Test Notebook',
  description: 'A test description',
  icon: 'BookOpen',
  color: 'from-blue-500 to-blue-600',
  sessionCount: 3,
  updatedAt: '2026-06-01',
  createdAt: '2026-06-01',
}

vi.mock('@/store/useStore', () => ({
  useStore: vi.fn((selector?) => {
    const state = {
      notebooks: [],
      sessions: [],
      dialog: { isOpen: false, type: null },
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

describe('NotebookCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders notebook title and description', () => {
    render(
      <MemoryRouter>
        <NotebookCard notebook={mockNotebook} />
      </MemoryRouter>
    )
    expect(screen.getByText('Test Notebook')).toBeInTheDocument()
    expect(screen.getByText('A test description')).toBeInTheDocument()
  })

  it('renders session count', () => {
    render(
      <MemoryRouter>
        <NotebookCard notebook={mockNotebook} />
      </MemoryRouter>
    )
    expect(screen.getByText('3 个课次')).toBeInTheDocument()
  })

  it('calls openDialog when edit button clicked', () => {
    const openDialogMock = vi.fn()
    vi.mocked(store.useStore).mockImplementation((selector?) => {
      const state = {
        notebooks: [],
        sessions: [],
        dialog: { isOpen: false, type: null },
        loading: false,
        error: null,
        openDialog: openDialogMock,
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
    })

    render(
      <MemoryRouter>
        <NotebookCard notebook={mockNotebook} />
      </MemoryRouter>
    )

    const editBtn = screen.getByTitle('编辑学科')
    fireEvent.click(editBtn)
    expect(openDialogMock).toHaveBeenCalledWith('notebook', undefined, mockNotebook)
  })

  it('calls removeNotebook when delete is confirmed', async () => {
    const removeNotebookMock = vi.fn().mockResolvedValue(undefined)
    vi.mocked(store.useStore).mockImplementation((selector?) => {
      const state = {
        notebooks: [],
        sessions: [],
        dialog: { isOpen: false, type: null },
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
        removeNotebook: removeNotebookMock,
        removeSession: vi.fn(),
      }
      return selector ? selector(state) : state
    })
    vi.stubGlobal('confirm', vi.fn(() => true))

    render(
      <MemoryRouter>
        <NotebookCard notebook={mockNotebook} />
      </MemoryRouter>
    )

    const deleteBtn = screen.getByTitle('删除学科')
    fireEvent.click(deleteBtn)
    expect(removeNotebookMock).toHaveBeenCalledWith('nb-1')
  })
})
