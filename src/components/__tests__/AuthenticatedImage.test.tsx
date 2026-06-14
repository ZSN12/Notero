import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { AuthenticatedImage } from '@/components/AuthenticatedImage'
import { preloadAuthenticatedImage, __resetImageCacheForTests } from '@/lib/imageCache'

describe('AuthenticatedImage', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    global.fetch = vi.fn()
    __resetImageCacheForTests()
  })

  const mockFetchSuccess = () => {
    vi.mocked(global.fetch).mockResolvedValue({
      ok: true,
      blob: () => Promise.resolve(new Blob(['image-data'], { type: 'image/png' })),
    } as Response)
  }

  it('renders image after fetching', async () => {
    mockFetchSuccess()
    render(<AuthenticatedImage src="/api/media/slides/s1/slide_01.png" alt="slide" />)
    await waitFor(() => {
      const img = screen.getByAltText('slide') as HTMLImageElement
      expect(img.src).toContain('blob:')
    })
    expect(global.fetch).toHaveBeenCalledTimes(1)
  })

  it('uses cached url on subsequent renders without fetching again', async () => {
    mockFetchSuccess()
    const { unmount } = render(<AuthenticatedImage src="/api/media/slides/s1/slide_01.png" alt="slide" />)
    await waitFor(() => {
      expect(screen.getByAltText('slide')).toBeInTheDocument()
    })
    expect(global.fetch).toHaveBeenCalledTimes(1)

    unmount()
    render(<AuthenticatedImage src="/api/media/slides/s1/slide_01.png" alt="slide" />)
    await waitFor(() => {
      expect(screen.getByAltText('slide')).toBeInTheDocument()
    })
    expect(global.fetch).toHaveBeenCalledTimes(1)
  })

  it('preloads image into cache', async () => {
    mockFetchSuccess()
    await preloadAuthenticatedImage('/api/media/slides/s1/slide_02.png')
    render(<AuthenticatedImage src="/api/media/slides/s1/slide_02.png" alt="slide" />)
    await waitFor(() => {
      expect(screen.getByAltText('slide')).toBeInTheDocument()
    })
    expect(global.fetch).toHaveBeenCalledTimes(1)
  })

  it('shows fallback on fetch failure', async () => {
    vi.mocked(global.fetch).mockResolvedValue({ ok: false, status: 404 } as Response)
    render(
      <AuthenticatedImage
        src="/api/media/slides/s1/missing.png"
        alt="slide"
        fallback={<div data-testid="fallback">failed</div>}
      />
    )
    await waitFor(() => {
      expect(screen.getByTestId('fallback')).toBeInTheDocument()
    })
  })
})
