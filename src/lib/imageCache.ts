import { authHeaders } from '@/services/api';

// Global cache for authenticated image blob URLs so that the same image is not
// fetched repeatedly when it is rendered multiple times (e.g. switching PPT
// slides back and forth).
const imageUrlCache = new Map<string, string>();

function cacheImageUrl(src: string, url: string) {
  imageUrlCache.set(src, url);
}

function getCachedImageUrl(src: string): string | undefined {
  return imageUrlCache.get(src);
}

function loadImageToCache(src: string): Promise<string | undefined> {
  return fetch(src, { headers: authHeaders() })
    .then((res) => {
      if (!res.ok) throw new Error(`Image request failed: ${res.status}`);
      return res.blob();
    })
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      cacheImageUrl(src, url);
      return url;
    });
}

// Preload an authenticated image into the global cache. Safe to call multiple
// times for the same src.
export function preloadAuthenticatedImage(src: string): Promise<string | undefined> {
  if (!src || src.startsWith('data:') || src.startsWith('blob:')) {
    return Promise.resolve(src || undefined);
  }
  const cached = getCachedImageUrl(src);
  if (cached) return Promise.resolve(cached);
  return loadImageToCache(src);
}

export function getAuthenticatedImageUrl(src: string): string | undefined {
  if (!src) return undefined;
  if (src.startsWith('data:') || src.startsWith('blob:')) return src;
  return getCachedImageUrl(src);
}

export function loadAndCacheAuthenticatedImage(src: string): Promise<string | undefined> {
  if (!src || src.startsWith('data:') || src.startsWith('blob:')) {
    return Promise.resolve(src || undefined);
  }
  return loadImageToCache(src);
}

function clearImageCache() {
  imageUrlCache.forEach((url) => {
    if (!url.startsWith('data:') && !url.startsWith('blob:')) {
      URL.revokeObjectURL(url);
    }
  });
  imageUrlCache.clear();
}

// Release all cached object URLs when the page unloads to avoid memory leaks.
if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', clearImageCache);
}

// Exposed only for tests.
export function __resetImageCacheForTests() {
  clearImageCache();
}
