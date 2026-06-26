export function stableTextId(prefix: string, index: number, text: string): string {
  const normalized = (text || '').replace(/\s+/g, '');
  let value = 2166136261;

  for (let i = 0; i < Math.min(normalized.length, 240); i += 1) {
    value ^= normalized.charCodeAt(i);
    value = Math.imul(value, 16777619) >>> 0;
  }

  return `${prefix}-${index}-${value.toString(16).padStart(8, '0')}`;
}
