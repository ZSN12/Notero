import { describe, it, expect } from 'vitest'
import { sanitizeHTML, escapeHtml } from '@/lib/sanitize'

describe('sanitizeHTML', () => {
  it('removes script tags', () => {
    const dirty = '<p>hello</p><script>alert("xss")</script>'
    const result = sanitizeHTML(dirty) as unknown as string
    expect(result).not.toContain('<script>')
    expect(result).toContain('<p>hello</p>')
  })

  it('removes event handlers', () => {
    const dirty = '<img src="x" onerror="alert(1)">'
    const result = sanitizeHTML(dirty) as unknown as string
    expect(result).not.toContain('onerror')
  })

  it('allows safe HTML', () => {
    const clean = '<strong>bold</strong> <em>italic</em>'
    const result = sanitizeHTML(clean) as unknown as string
    expect(result).toContain('<strong>bold</strong>')
    expect(result).toContain('<em>italic</em>')
  })

  it('returns empty string for empty input', () => {
    const result = sanitizeHTML('') as unknown as string
    expect(result).toBe('')
  })
})

describe('escapeHtml', () => {
  it('escapes special HTML characters', () => {
    expect(escapeHtml('<p>hello & "world"</p>')).toBe('&lt;p&gt;hello &amp; &quot;world&quot;&lt;/p&gt;')
  })

  it('escapes single quotes', () => {
    expect(escapeHtml("it's")).toBe('it&#039;s')
  })

  it('returns plain text unchanged', () => {
    expect(escapeHtml('plain text 123')).toBe('plain text 123')
  })
})
