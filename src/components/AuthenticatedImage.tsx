import { useEffect, useState, type ImgHTMLAttributes, type ReactNode } from 'react';
import {
  getAuthenticatedImageUrl,
  loadAndCacheAuthenticatedImage,
} from '@/lib/imageCache';

interface AuthenticatedImageProps extends Omit<ImgHTMLAttributes<HTMLImageElement>, 'src'> {
  src: string;
  fallback?: ReactNode;
}

export function AuthenticatedImage({ src, fallback = null, onError, ...props }: AuthenticatedImageProps) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!src) {
      setObjectUrl(null);
      setFailed(true);
      return;
    }

    const cached = getAuthenticatedImageUrl(src);
    if (cached) {
      setObjectUrl(cached);
      setFailed(false);
      return;
    }

    let cancelled = false;

    setFailed(false);
    setObjectUrl(null);

    loadAndCacheAuthenticatedImage(src)
      .then((url) => {
        if (cancelled) return;
        setObjectUrl(url || null);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
    };
  }, [src]);

  if (failed) return <>{fallback}</>;
  if (!objectUrl) return <>{fallback}</>;

  return (
    <img
      {...props}
      src={objectUrl}
      onError={(event) => {
        setFailed(true);
        onError?.(event);
      }}
    />
  );
}
