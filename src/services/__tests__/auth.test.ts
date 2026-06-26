import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  getToken,
  setToken,
  clearToken,
  isAuthenticated,
  login,
  register,
  logout,
  resetPassword,
  getProfile,
  updateProfile,
  changePassword,
  uploadAvatar,
} from '@/services/auth'


describe('auth token management', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.resetAllMocks()
  })

  it('getToken returns null when no token', () => {
    expect(getToken()).toBeNull()
    expect(isAuthenticated()).toBe(false)
  })

  it('setToken and getToken work', () => {
    setToken('abc123')
    expect(getToken()).toBe('abc123')
    expect(isAuthenticated()).toBe(true)
  })

  it('clearToken removes token and cookie', () => {
    setToken('abc123')
    clearToken()
    expect(getToken()).toBeNull()
    expect(isAuthenticated()).toBe(false)
  })
})

describe('login', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.resetAllMocks()
  })

  it('returns token on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ access_token: 'tok123' }),
    }))
    const token = await login('test@example.com', 'password')
    expect(token).toBe('tok123')
    expect(getToken()).toBe('tok123')
  })

  it('throws on failed login', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Invalid credentials' }),
    }))
    await expect(login('test@example.com', 'wrong')).rejects.toThrow('Invalid credentials')
  })

  it('throws readable message when detail is an object', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: { msg: '用户名已存在' } }),
    }))
    await expect(login('test@example.com', 'password')).rejects.toThrow('用户名已存在')
  })

  it('throws readable message when detail is a validation array', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({
        detail: [
          { msg: '邮箱格式不正确', loc: ['body', 'email'] },
          { msg: '密码太短', loc: ['body', 'password'] },
        ],
      }),
    }))
    await expect(login('test@example.com', 'password')).rejects.toThrow('邮箱格式不正确；密码太短')
  })

  it('strips pydantic style prefixes from validation messages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({
        detail: [
          { msg: 'Value error, Invalid email format', loc: ['body', 'email'] },
          { msg: 'Value error, Password must be at least 8 characters', loc: ['body', 'password'] },
        ],
      }),
    }))
    await expect(login('test@example.com', 'password')).rejects.toThrow('Invalid email format；Password must be at least 8 characters')
  })

  it('throws on network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network error')))
    await expect(login('test@example.com', 'password')).rejects.toThrow('无法连接到服务器')
  })

  it('throws timeout error when aborted', async () => {
    const abortError = new Error('Aborted')
    abortError.name = 'AbortError'
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abortError))
    await expect(login('test@example.com', 'password')).rejects.toThrow('请求超时')
  })
})

describe('register', () => {
  it('resolves on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }))
    await expect(register('user', 'test@example.com', 'password')).resolves.toBeUndefined()
  })

  it('throws on failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Email already exists' }),
    }))
    await expect(register('user', 'test@example.com', 'password')).rejects.toThrow('Email already exists')
  })
})

describe('logout', () => {
  it('clears token and redirects', () => {
    setToken('tok123')
    logout()
    expect(getToken()).toBeNull()
    expect(window.location.href).toBe('/login')
  })
})

describe('resetPassword', () => {
  it('resolves on success', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }))
    await expect(resetPassword('test@example.com', 'newpassword')).resolves.toBeUndefined()
  })

  it('throws on failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'User not found' }),
    }))
    await expect(resetPassword('test@example.com', 'newpassword')).rejects.toThrow('User not found')
  })
})

describe('getProfile', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('returns profile when authenticated', async () => {
    setToken('tok123')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: 'u1', email: 'test@example.com', username: 'tester' }),
    }))
    const profile = await getProfile()
    expect(profile.email).toBe('test@example.com')
  })

  it('throws when not authenticated', async () => {
    await expect(getProfile()).rejects.toThrow('Not authenticated')
  })

  it('throws on failed fetch', async () => {
    setToken('tok123')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    await expect(getProfile()).rejects.toThrow('Failed to fetch profile')
  })
})

describe('updateProfile', () => {
  it('returns updated profile', async () => {
    setToken('tok123')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: 'u1', email: 'test@example.com', username: 'newname' }),
    }))
    const profile = await updateProfile('newname')
    expect(profile.username).toBe('newname')
  })

  it('throws on failure', async () => {
    setToken('tok123')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Invalid username' }),
    }))
    await expect(updateProfile('x')).rejects.toThrow('Invalid username')
  })
})

describe('changePassword', () => {
  it('resolves on success', async () => {
    setToken('tok123')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }))
    await expect(changePassword('old', 'new')).resolves.toBeUndefined()
  })

  it('throws on failure', async () => {
    setToken('tok123')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Wrong old password' }),
    }))
    await expect(changePassword('old', 'new')).rejects.toThrow('Wrong old password')
  })
})

describe('uploadAvatar', () => {
  it('returns avatar url on success', async () => {
    setToken('tok123')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ avatar_url: 'http://example.com/avatar.png' }),
    }))
    const file = new File(['data'], 'avatar.png', { type: 'image/png' })
    const url = await uploadAvatar(file)
    expect(url).toBe('http://example.com/avatar.png')
  })

  it('throws on failure', async () => {
    setToken('tok123')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'Invalid image' }),
    }))
    const file = new File(['data'], 'avatar.png', { type: 'image/png' })
    await expect(uploadAvatar(file)).rejects.toThrow('Invalid image')
  })
})
