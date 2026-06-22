import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useStore } from '@/store/useStore'
import * as api from '@/services/api'

const mockNotebooks = [
  { id: 'nb-1', title: 'Notebook 1', description: '', icon: 'BookOpen', color: 'from-blue-500 to-blue-600', sessionCount: 2, updatedAt: '2026-06-01', createdAt: '2026-06-01' },
]

const mockSessions = [
  { id: 's-1', notebookId: 'nb-1', title: 'Session 1', summary: '', keywords: [], icon: 'BookOpen', date: '2026-06-01', duration: '30min', content: '', status: 'active', createdAt: '2026-06-01' },
]

describe('useStore', () => {
  beforeEach(() => {
    // Reset store state before each test
    useStore.setState({
      notebooks: [],
      sessions: [],
      dialog: { isOpen: false, type: null },
      loading: false,
      error: null,
    })
    vi.resetAllMocks()
  })

  it('has initial state', () => {
    const state = useStore.getState()
    expect(state.notebooks).toEqual([])
    expect(state.sessions).toEqual([])
    expect(state.loading).toBe(false)
    expect(state.error).toBeNull()
    expect(state.dialog.isOpen).toBe(false)
  })

  it('openDialog and closeDialog work', () => {
    const { openDialog, closeDialog } = useStore.getState()
    openDialog('notebook')
    expect(useStore.getState().dialog).toEqual({
      isOpen: true,
      type: 'notebook',
      notebookId: undefined,
      editingNotebook: undefined,
    })
    closeDialog()
    expect(useStore.getState().dialog.isOpen).toBe(false)
    expect(useStore.getState().dialog.type).toBeNull()
  })

  it('loadNotebooks fetches and sets notebooks', async () => {
    vi.spyOn(api, 'fetchNotebooks').mockResolvedValue(mockNotebooks)
    await useStore.getState().loadNotebooks()
    expect(useStore.getState().notebooks).toEqual(mockNotebooks)
    expect(useStore.getState().loading).toBe(false)
    expect(useStore.getState().error).toBeNull()
  })

  it('loadNotebooks handles errors', async () => {
    vi.spyOn(api, 'fetchNotebooks').mockRejectedValue(new Error('Network error'))
    await useStore.getState().loadNotebooks()
    expect(useStore.getState().notebooks).toEqual([])
    expect(useStore.getState().error).toBe('Network error')
    expect(useStore.getState().loading).toBe(false)
  })

  it('loadSessions fetches and sets sessions', async () => {
    vi.spyOn(api, 'fetchSessions').mockResolvedValue(mockSessions)
    await useStore.getState().loadSessions('nb-1')
    expect(useStore.getState().sessions).toEqual(mockSessions)
    expect(useStore.getState().loading).toBe(false)
  })

  it('createNotebook adds notebook to state', async () => {
    const newNotebook = { id: 'nb-2', title: 'New NB', description: '', icon: 'Brain', color: 'from-violet-500 to-violet-600', sessionCount: 0, updatedAt: '2026-06-02', createdAt: '2026-06-02' }
    vi.spyOn(api, 'createNotebook').mockResolvedValue(newNotebook)
    await useStore.getState().createNotebook('New NB')
    expect(useStore.getState().notebooks).toContainEqual(newNotebook)
  })

  it('updateNotebook updates existing notebook', async () => {
    useStore.setState({ notebooks: mockNotebooks })
    const updated = { ...mockNotebooks[0], title: 'Updated Title' }
    vi.spyOn(api, 'updateNotebook').mockResolvedValue(updated)
    await useStore.getState().updateNotebook('nb-1', 'Updated Title')
    expect(useStore.getState().notebooks[0].title).toBe('Updated Title')
  })

  it('createSession adds session and updates notebook sessionCount', async () => {
    useStore.setState({ notebooks: mockNotebooks })
    const newSession = { id: 's-2', notebookId: 'nb-1', title: 'New Session', summary: '', keywords: [], icon: 'BookOpen', date: '2026-06-02', duration: '30min', content: '', status: 'active', createdAt: '2026-06-02' }
    vi.spyOn(api, 'createSession').mockResolvedValue(newSession)
    await useStore.getState().createSession('nb-1', 'New Session')
    expect(useStore.getState().sessions).toContainEqual(newSession)
    expect(useStore.getState().notebooks[0].sessionCount).toBe(3)
  })

  it('removeNotebook filters out deleted notebook and its sessions', async () => {
    useStore.setState({ notebooks: mockNotebooks, sessions: mockSessions })
    vi.spyOn(api, 'deleteNotebook').mockResolvedValue(undefined)
    await useStore.getState().removeNotebook('nb-1')
    expect(useStore.getState().notebooks).toHaveLength(0)
    expect(useStore.getState().sessions).toHaveLength(0)
  })

  it('removeSession filters out deleted session', async () => {
    useStore.setState({ notebooks: mockNotebooks, sessions: mockSessions })
    vi.spyOn(api, 'deleteSession').mockResolvedValue(undefined)
    vi.spyOn(api, 'fetchSessions').mockResolvedValue([])
    await useStore.getState().removeSession('nb-1', 's-1')
    expect(useStore.getState().sessions).toHaveLength(0)
  })

  it('createNotebook handles errors', async () => {
    vi.spyOn(api, 'createNotebook').mockRejectedValue(new Error('Server error'))
    await expect(useStore.getState().createNotebook('New')).rejects.toThrow('Server error')
    expect(useStore.getState().error).toBe('Server error')
  })

  it('updateNotebook handles errors', async () => {
    useStore.setState({ notebooks: mockNotebooks })
    vi.spyOn(api, 'updateNotebook').mockRejectedValue(new Error('Update failed'))
    await expect(useStore.getState().updateNotebook('nb-1', 'Updated')).rejects.toThrow('Update failed')
    expect(useStore.getState().error).toBe('Update failed')
  })

  it('createSession handles errors', async () => {
    vi.spyOn(api, 'createSession').mockRejectedValue(new Error('Create failed'))
    await expect(useStore.getState().createSession('nb-1', 'New')).rejects.toThrow('Create failed')
    expect(useStore.getState().error).toBe('Create failed')
  })

  it('removeNotebook handles errors', async () => {
    useStore.setState({ notebooks: mockNotebooks })
    vi.spyOn(api, 'deleteNotebook').mockRejectedValue(new Error('Delete failed'))
    await expect(useStore.getState().removeNotebook('nb-1')).rejects.toThrow('Delete failed')
    expect(useStore.getState().error).toBe('Delete failed')
  })

  it('removeSession handles errors', async () => {
    useStore.setState({ notebooks: mockNotebooks, sessions: mockSessions })
    vi.spyOn(api, 'deleteSession').mockRejectedValue(new Error('Delete failed'))
    await expect(useStore.getState().removeSession('nb-1', 's-1')).rejects.toThrow('Delete failed')
    expect(useStore.getState().error).toBe('Delete failed')
  })

  it('removeSession keeps session removed when list refresh fails', async () => {
    useStore.setState({ notebooks: mockNotebooks, sessions: mockSessions })
    vi.spyOn(api, 'deleteSession').mockResolvedValue(undefined)
    vi.spyOn(api, 'fetchSessions').mockRejectedValue(new Error('Refresh failed'))
    await expect(useStore.getState().removeSession('nb-1', 's-1')).rejects.toThrow('列表刷新失败')
    expect(useStore.getState().sessions).toHaveLength(0)
    expect(useStore.getState().error).toBe('列表刷新失败')
  })

  it('loadSessions handles errors', async () => {
    vi.spyOn(api, 'fetchSessions').mockRejectedValue(new Error('Network error'))
    await useStore.getState().loadSessions('nb-1')
    expect(useStore.getState().sessions).toEqual([])
    expect(useStore.getState().error).toBe('Network error')
    expect(useStore.getState().loading).toBe(false)
  })
})
