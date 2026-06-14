import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  mapBackendNotebook,
  mapBackendSession,
  getMediaUrl,
  API_BASE,
  fetchNotebooks,
  createNotebook,
  deleteNotebook,
  updateNotebook,
  fetchNotebookDetail,
  fetchSessions,
  fetchSessionById,
  createSession,
  deleteSession,
  updateSessionDuration,
  fetchNote,
  updateNote,
  finishRecording,
  deleteAudio,
  getAudioUrl,
  rebuildSessionVectorIndex,
  getSessionVectorStatus,
  searchVectors,
  getSessionMindMap,
  generateSessionMindMap,
  getQuizBankStatus,
  getSessionQuizzes,
  submitQuizAnswers,
  runAllAgents,
  getAgentTasks,
} from '@/services/api'
import * as auth from '@/services/auth'

describe('mapBackendNotebook', () => {
  it('maps backend fields to frontend Notebook', () => {
    const bn = {
      id: 'nb-1',
      user_id: 'u-1',
      title: 'Test Notebook',
      description: 'A description',
      icon: 'Brain',
      color: 'from-blue-500 to-blue-600',
      session_count: 5,
      created_at: '2026-06-01T00:00:00Z',
    }
    const result = mapBackendNotebook(bn)
    expect(result.id).toBe('nb-1')
    expect(result.title).toBe('Test Notebook')
    expect(result.description).toBe('A description')
    expect(result.icon).toBe('Brain')
    expect(result.color).toBe('from-blue-500 to-blue-600')
    expect(result.sessionCount).toBe(5)
    expect(result.updatedAt).toBe('2026-06-01')
  })

  it('falls back to hashed color when color is null', () => {
    const bn = {
      id: 'nb-2',
      user_id: 'u-1',
      title: 'No Color',
      description: null,
      icon: null,
      color: null,
      session_count: 0,
      created_at: '2026-06-01T00:00:00Z',
    }
    const result = mapBackendNotebook(bn)
    expect(result.color).toMatch(/^from-/)
    expect(result.icon).toBe('BookOpen')
  })
})

describe('mapBackendSession', () => {
  it('maps backend session fields', () => {
    const bs = {
      id: 's-1',
      notebook_id: 'nb-1',
      title: 'Session 1',
      keywords: ['a', 'b'],
      status: 'completed',
      created_at: '2026-06-02T00:00:00Z',
    }
    const result = mapBackendSession(bs)
    expect(result.id).toBe('s-1')
    expect(result.notebookId).toBe('nb-1')
    expect(result.title).toBe('Session 1')
    expect(result.keywords).toEqual(['a', 'b'])
    expect(result.date).toBe('2026-06-02')
    expect(result.duration).toBe('00:00:00')
  })
})

describe('getMediaUrl', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('returns relative path with API base', () => {
    vi.spyOn(auth, 'getToken').mockReturnValue('my-token')
    const url = getMediaUrl('/uploads/image.png')
    expect(url).toContain('/uploads/image.png')
    expect(url).not.toContain('token=')
  })

  it('does not modify absolute URLs', () => {
    vi.spyOn(auth, 'getToken').mockReturnValue('my-token')
    const url = getMediaUrl('https://cdn.example.com/img.png')
    expect(url).toBe('https://cdn.example.com/img.png')
  })

  it('works without token', () => {
    vi.spyOn(auth, 'getToken').mockReturnValue(null)
    const url = getMediaUrl('/uploads/image.png')
    expect(url).not.toContain('token=')
  })
})

describe('API_BASE', () => {
  it('is defined', () => {
    expect(API_BASE).toBeDefined()
    expect(typeof API_BASE).toBe('string')
  })
})

// ── Core request behavior via public APIs ──

describe('request core behavior (via fetchNotebooks)', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    localStorage.clear()
  })

  it('returns parsed data on 200', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [{ id: 'nb-1', title: 'T', user_id: 'u1', description: null, icon: null, color: null, session_count: 0, created_at: '2026-06-01T00:00:00Z' }],
    }))
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
    const data = await fetchNotebooks()
    expect(data).toHaveLength(1)
    expect(data[0].title).toBe('T')
  })

  it('clears token and redirects on 401', async () => {
    const clearSpy = vi.spyOn(auth, 'clearToken')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      text: async () => 'Unauthorized',
    }))
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
    await expect(fetchNotebooks()).rejects.toThrow()
    expect(clearSpy).toHaveBeenCalled()
  })

  it('throws timeout error on AbortError', async () => {
    const abortErr = new DOMException('Timeout', 'AbortError')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abortErr))
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
    await expect(fetchNotebooks()).rejects.toThrow('请求超时')
  })

  it('returns undefined on 204', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      text: async () => '',
    }))
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
    await expect(deleteNotebook('nb-1')).resolves.toBeUndefined()
  })

  it('parses detail string from error JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      text: async () => JSON.stringify({ detail: 'Bad request' }),
    }))
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
    await expect(fetchNotebooks()).rejects.toThrow('Bad request')
  })

  it('parses detail array from error JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: async () => JSON.stringify({ detail: [{ msg: 'Field required' }] }),
    }))
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
    await expect(fetchNotebooks()).rejects.toThrow('Field required')
  })
})

// ── Notebook API ──

describe('Notebook API', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
  })

  it('fetchNotebookDetail returns data on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'nb-1', title: 'T', user_id: 'u1', description: null, icon: null, color: null, session_count: 0, created_at: '2026-06-01T00:00:00Z' }),
    }))
    const data = await fetchNotebookDetail('nb-1')
    expect(data?.title).toBe('T')
  })

  it('fetchNotebookDetail returns null on error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, text: async () => 'Not found' }))
    const data = await fetchNotebookDetail('nb-1')
    expect(data).toBeNull()
  })

  it('createNotebook maps response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'nb-2', title: 'New', user_id: 'u1', description: null, icon: null, color: null, session_count: 0, created_at: '2026-06-01T00:00:00Z' }),
    }))
    const nb = await createNotebook('New')
    expect(nb.title).toBe('New')
  })

  it('updateNotebook maps response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ id: 'nb-1', title: 'Updated', user_id: 'u1', description: null, icon: null, color: null, session_count: 0, created_at: '2026-06-01T00:00:00Z' }),
    }))
    const nb = await updateNotebook('nb-1', 'Updated')
    expect(nb.title).toBe('Updated')
  })
})

// ── Session API ──

describe('Session API', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
  })

  it('fetchSessions maps array', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { id: 's-1', notebook_id: 'nb-1', title: 'S1', keywords: [], status: 'done', created_at: '2026-06-01T00:00:00Z' },
      ],
    }))
    const list = await fetchSessions('nb-1')
    expect(list).toHaveLength(1)
    expect(list[0].title).toBe('S1')
  })

  it('fetchSessionById returns mapped session', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: 's-1', notebook_id: 'nb-1', title: 'S1', keywords: [], status: 'done', created_at: '2026-06-01T00:00:00Z' }),
    }))
    const s = await fetchSessionById('s-1')
    expect(s?.title).toBe('S1')
  })

  it('fetchSessionById returns null on error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, text: async () => '' }))
    const s = await fetchSessionById('s-1')
    expect(s).toBeNull()
  })

  it('createSession maps response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: 's-2', notebook_id: 'nb-1', title: 'New', keywords: [], status: 'pending', created_at: '2026-06-01T00:00:00Z' }),
    }))
    const s = await createSession('nb-1', 'New')
    expect(s.title).toBe('New')
  })

  it('deleteSession resolves on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 204, text: async () => '' }))
    await expect(deleteSession('s-1')).resolves.toBeUndefined()
  })

  it('updateSessionDuration sends formatted duration', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 204, text: async () => '' })
    vi.stubGlobal('fetch', fetchMock)
    await updateSessionDuration('s-1', 3661000)
    const call = fetchMock.mock.calls[0]
    const body = JSON.parse(call[1].body)
    expect(body.duration).toBe('01:01:01')
  })
})

// ── Note API ──

describe('Note API', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
  })

  it('fetchNote returns data on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: 'n-1', session_id: 's-1', content: 'hello', transcript: null, ppt_images: null, vocabulary: null, created_at: '2026-06-01T00:00:00Z' }),
    }))
    const note = await fetchNote('s-1')
    expect(note?.content).toBe('hello')
  })

  it('fetchNote throws on error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, text: async () => '' }))
    await expect(fetchNote('s-1')).rejects.toThrow()
  })

  it('updateNote returns data on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: 'n-1', session_id: 's-1', content: 'updated', transcript: null, ppt_images: null, vocabulary: null, created_at: '2026-06-01T00:00:00Z' }),
    }))
    const note = await updateNote('s-1', 'updated')
    expect(note?.content).toBe('updated')
  })

  it('finishRecording returns data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: 'success', audio_path: '/audio.wav', note: null }),
    }))
    const res = await finishRecording('s-1')
    expect(res.status).toBe('success')
    expect(res.audio_path).toBe('/audio.wav')
  })

  it('finishRecording returns fallback on error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('fail')))
    const res = await finishRecording('s-1')
    expect(res.status).toBe('error')
    expect(res.audio_path).toBeNull()
  })

  it('deleteAudio returns true on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 204, text: async () => '' }))
    expect(await deleteAudio('s-1')).toBe(true)
  })

  it('deleteAudio returns false on error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500, text: async () => '' }))
    expect(await deleteAudio('s-1')).toBe(false)
  })

  it('getAudioUrl returns media url', () => {
    const url = getAudioUrl('s-1')
    expect(url).toContain('/api/media/audio/s-1.wav')
  })
})

// ── Vector API ──

describe('Vector API', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
  })

  it('rebuildSessionVectorIndex returns status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: 's-1', chunk_count: 10, status: 'indexed' }),
    }))
    const res = await rebuildSessionVectorIndex('s-1')
    expect(res.chunk_count).toBe(10)
  })

  it('getSessionVectorStatus returns status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: 's-1', chunk_count: 5, has_content: true, status: 'indexed' }),
    }))
    const res = await getSessionVectorStatus('s-1')
    expect(res.status).toBe('indexed')
  })

  it('searchVectors returns results', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        results: [{ chunk_id: 'c1', notebook_id: 'nb-1', notebook_title: 'NB', session_id: 's-1', session_title: 'S', source_type: 'note', snippet: 'hello', score: 0.9, metadata: {} }],
        total: 1,
      }),
    }))
    const res = await searchVectors('query', 's-1', 'nb-1', 5)
    expect(res.total).toBe(1)
    expect(res.results[0].snippet).toBe('hello')
  })
})

// ── MindMap API ──

describe('MindMap API', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
  })

  it('getSessionMindMap returns data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: 's-1', status: 'ready', mind_map: { title: 'Map', nodes: [] } }),
    }))
    const res = await getSessionMindMap('s-1')
    expect(res.status).toBe('ready')
  })

  it('generateSessionMindMap returns data', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: 's-1', status: 'generating', mind_map: null }),
    }))
    const res = await generateSessionMindMap('s-1')
    expect(res.status).toBe('generating')
  })
})

// ── Quiz API ──

describe('Quiz API', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
  })

  it('getQuizBankStatus returns status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: 's-1', status: 'ready', question_count: 5 }),
    }))
    const res = await getQuizBankStatus('s-1')
    expect(res.question_count).toBe(5)
  })

  it('getSessionQuizzes returns list', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        { quiz_id: 'q1', title: 'Quiz 1', question_count: 3, questions: [], submitted: false },
      ],
    }))
    const list = await getSessionQuizzes('s-1')
    expect(list).toHaveLength(1)
  })

  it('submitQuizAnswers returns result', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ score: 2, total: 3, percentage: 66.7, results: [] }),
    }))
    const res = await submitQuizAnswers('s-1', 'q1', { a1: 'A' })
    expect(res.score).toBe(2)
  })
})

// ── Agent API ──

describe('Agent API', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(auth, 'getToken').mockReturnValue('tok')
  })

  it('runAllAgents returns workflow', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ workflow_id: 'w1', session_id: 's-1', agents: [{ role: 'mindmap', task_id: 't1', status: 'pending', progress: 0, error: null }] }),
    }))
    const res = await runAllAgents('s-1')
    expect(res.workflow_id).toBe('w1')
    expect(res.agents).toHaveLength(1)
  })

  it('getAgentTasks returns tasks', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ session_id: 's-1', agents: [{ task_id: 't1', task_type: 'agent_mindmap', status: 'success', progress: 1, error: null, created_at: '2026-06-01T00:00:00Z' }] }),
    }))
    const res = await getAgentTasks('s-1')
    expect(res.agents).toHaveLength(1)
    expect(res.agents[0].status).toBe('success')
  })
})
