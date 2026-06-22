import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import SessionCard from '@/components/SessionCard'
import * as store from '@/store/useStore'

const mockSession = {
  id: 's-1',
  notebookId: 'nb-1',
  title: 'Test Session',
  summary: '',
  keywords: [],
  icon: 'FileText',
  date: '2026-06-01',
  duration: '30min',
  content: '',
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

describe('SessionCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders session title', () => {
    render(
      <MemoryRouter>
        <SessionCard session={mockSession} notebookId="nb-1" />
      </MemoryRouter>
    )
    expect(screen.getByText('Test Session')).toBeInTheDocument()
  })

  it('calls removeSession when delete is confirmed', async () => {
    const removeSessionMock = vi.fn().mockResolvedValue(undefined)
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
        removeNotebook: vi.fn(),
        removeSession: removeSessionMock,
      }
      return selector ? selector(state) : state
    })
    vi.stubGlobal('confirm', vi.fn(() => true))

    render(
      <MemoryRouter>
        <SessionCard session={mockSession} notebookId="nb-1" />
      </MemoryRouter>
    )

    const deleteBtn = screen.getByTitle('删除课次')
    fireEvent.click(deleteBtn)
    expect(removeSessionMock).toHaveBeenCalledWith('nb-1', 's-1')
  })
})
