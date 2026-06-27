export const API_BASE =
  import.meta.env.VITE_API_PROXY_TARGET
    ? ''
    : import.meta.env.VITE_API_BASE_URL ??
      import.meta.env.VITE_API_BASE ??
      `${window.location.protocol}//${window.location.hostname}:8003`;
