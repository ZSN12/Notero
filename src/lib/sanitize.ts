import DOMPurify from 'dompurify';

export function sanitizeHTML(html: string): TrustedHTML {
  return DOMPurify.sanitize(html) as unknown as TrustedHTML;
}

export function stripHTML(html: string): string {
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  return tmp.textContent || tmp.innerText || '';
}

export function escapeHtml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
