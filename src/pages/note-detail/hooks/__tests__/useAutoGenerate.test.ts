import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useAutoGenerate } from '../useAutoGenerate'
import type { SessionProcessingStatus } from '@/services/api'

// Mock API module
vi.mock('@/services/api', () => ({
  runAllAgents: vi.fn(),
}))

import { runAllAgents } from '@/services/api'

function makeStatus(
  stages: Partial<SessionProcessingStatus['stages']>,
): SessionProcessingStatus {
  return {
    session_id: 's1',
    overall_status: 'idle',
    stages: {
      upload_transcribe: { status: 'idle', progress: 0, message: null, error_message: null, content_hash: null, started_at: null, finished_at: null },
      recording_finalize: { status: 'idle', progress: 0, message: null, error_message: null, content_hash: null, started_at: null, finished_at: null },
      transcript_finalize: { status: 'ready', progress: 1, message: null, error_message: null, content_hash: 'abc', started_at: null, finished_at: null },
      transcript_organize: { status: 'ready', progress: 1, message: null, error_message: null, content_hash: 'abc', started_at: null, finished_at: null },
      vector_index: { status: 'ready', progress: 1, message: null, error_message: null, content_hash: 'abc', started_at: null, finished_at: null },
      mindmap: { status: 'idle', progress: 0, message: null, error_message: null, content_hash: null, started_at: null, finished_at: null },
      quiz_bank: { status: 'idle', progress: 0, message: null, error_message: null, content_hash: null, started_at: null, finished_at: null },
      ...stages,
    },
    can_auto_generate: true,
    can_ask_rag: true,
    needs_user_action: false,
    latest_tasks: [],
    vector_chunks_count: 0,
  }
}

describe('useAutoGenerate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('reads auto-generate setting from localStorage', () => {
    localStorage.setItem('notero_auto_generate_study_materials', 'false')
    const { result } = renderHook(() => useAutoGenerate('s1', null))
    expect(result.current.state.autoGenerateStudyMaterials).toBe(false)
  })

  it('defaults to true when localStorage is empty', () => {
    const { result } = renderHook(() => useAutoGenerate('s1', null))
    expect(result.current.state.autoGenerateStudyMaterials).toBe(true)
  })

  it('persists setting to localStorage', () => {
    const { result } = renderHook(() => useAutoGenerate('s1', null))
    act(() => {
      result.current.actions.setAutoGenerateStudyMaterials(false)
    })
    expect(localStorage.getItem('notero_auto_generate_study_materials')).toBe('false')
    expect(result.current.state.autoGenerateStudyMaterials).toBe(false)
  })

  it('shows running toast when any agent is running', () => {
    const status = makeStatus({
      mindmap: { status: 'running', progress: 0.5, message: null, error_message: null, content_hash: null, started_at: null, finished_at: null },
    })
    const { result } = renderHook(() => useAutoGenerate('s1', status))
    expect(result.current.state.autoGenerateToast).toBe('正在生成学习资料...')
  })

  it('shows success toast when all agents are ready', async () => {
    vi.mocked(runAllAgents).mockResolvedValue({ workflow_id: 'wf-1', session_id: 's1', agents: [] })
    const status = makeStatus({
      mindmap: { status: 'ready', progress: 1, message: null, error_message: null, content_hash: 'h2', started_at: null, finished_at: null },
      quiz_bank: { status: 'ready', progress: 1, message: null, error_message: null, content_hash: 'h3', started_at: null, finished_at: null },
    })
    const { result } = renderHook(() => useAutoGenerate('s1', status))

    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.state.autoGenerateToast).toBe('学习资料生成完成')
  })

  it('shows error toast when any agent fails', async () => {
    vi.mocked(runAllAgents).mockResolvedValue({ workflow_id: 'wf-1', session_id: 's1', agents: [] })
    const status = makeStatus({
      mindmap: { status: 'error', progress: 1, message: null, error_message: 'fail', content_hash: null, started_at: null, finished_at: null },
      quiz_bank: { status: 'ready', progress: 1, message: null, error_message: null, content_hash: 'h3', started_at: null, finished_at: null },
    })
    const { result } = renderHook(() => useAutoGenerate('s1', status))

    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.state.autoGenerateToast).toBe('导图生成失败，可手动重试')
  })

  it('clears toast after timeout', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.mocked(runAllAgents).mockResolvedValue({ workflow_id: 'wf-1', session_id: 's1', agents: [] })
    const status = makeStatus({
      mindmap: { status: 'ready', progress: 1, message: null, error_message: null, content_hash: 'h2', started_at: null, finished_at: null },
      quiz_bank: { status: 'ready', progress: 1, message: null, error_message: null, content_hash: 'h3', started_at: null, finished_at: null },
    })
    const { result } = renderHook(() => useAutoGenerate('s1', status))

    await act(async () => {
      await Promise.resolve()
    })
    expect(result.current.state.autoGenerateToast).toBe('学习资料生成完成')

    act(() => {
      vi.advanceTimersByTime(4001)
    })
    expect(result.current.state.autoGenerateToast).toBeNull()
    vi.useRealTimers()
  })

  it('auto-triggers agents when transcript and vector index are ready', async () => {
    vi.mocked(runAllAgents).mockResolvedValueOnce({ workflow_id: 'wf-1', session_id: 's1', agents: [] })
    const status = makeStatus({})
    renderHook(() => useAutoGenerate('s1', status))

    await waitFor(() => {
      expect(runAllAgents).toHaveBeenCalledWith('s1', ['mindmap', 'quiz'])
    })
  })

  it('does not auto-trigger when auto-generate is disabled', () => {
    localStorage.setItem('notero_auto_generate_study_materials', 'false')
    const status = makeStatus({})
    renderHook(() => useAutoGenerate('s1', status))
    expect(runAllAgents).not.toHaveBeenCalled()
  })

  it('handleTriggerAgents calls runAllAgents with default roles', async () => {
    vi.mocked(runAllAgents).mockResolvedValueOnce({ workflow_id: 'wf-1', session_id: 's1', agents: [] })
    const { result } = renderHook(() => useAutoGenerate('s1', null))

    await act(async () => {
      await result.current.actions.handleTriggerAgents('s1')
    })

    expect(runAllAgents).toHaveBeenCalledWith('s1', ['mindmap', 'quiz'])
  })

  it('handleTriggerAgents calls runAllAgents with given roles', async () => {
    vi.mocked(runAllAgents).mockResolvedValueOnce({ workflow_id: 'wf-1', session_id: 's1', agents: [] })
    const { result } = renderHook(() => useAutoGenerate('s1', null))

    await act(async () => {
      await result.current.actions.handleTriggerAgents('s1', ['mindmap'])
    })

    expect(runAllAgents).toHaveBeenCalledWith('s1', ['mindmap'])
  })
})
