import { useRef, useState, useEffect, useCallback } from 'react';
import { Palette } from 'lucide-react';

const PRESET_COLORS = [
  '#ef4444', // red
  '#f97316', // orange
  '#f59e0b', // amber
  '#84cc16', // lime
  '#10b981', // emerald
  '#06b6d4', // cyan
  '#3b82f6', // blue
  '#8b5cf6', // violet
  '#d946ef', // fuchsia
  '#64748b', // slate
];

const STORAGE_KEY = 'nootbook-recent-colors';
const DEFAULT_RECENT = ['#ef4444', '#3b82f6'];
const MAX_RECENT = 2;

interface ColorPickerProps {
  value?: string;
  onChange: (color: string) => void;
  className?: string;
}

function readRecent(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_RECENT;
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length > 0) {
      return parsed.slice(0, MAX_RECENT);
    }
  } catch {
    // ignore
  }
  return DEFAULT_RECENT;
}

function writeRecent(colors: string[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(colors.slice(0, MAX_RECENT)));
  } catch {
    // ignore
  }
}

export function ColorPicker({ value, onChange, className = '' }: ColorPickerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const savedRangeRef = useRef<Range | null>(null);
  const [open, setOpen] = useState(false);
  const [recent, setRecent] = useState<string[]>(() => readRecent());

  useEffect(() => {
    writeRecent(recent);
  }, [recent]);

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const selection = window.getSelection();
    if (selection && selection.rangeCount > 0) {
      savedRangeRef.current = selection.getRangeAt(0).cloneRange();
    }
    setOpen((prev) => !prev);
  }, []);

  const applyColor = useCallback(
    (color: string) => {
      if (savedRangeRef.current) {
        const selection = window.getSelection();
        if (selection) {
          selection.removeAllRanges();
          selection.addRange(savedRangeRef.current);
        }
        savedRangeRef.current = null;
      }
      setRecent((prev) => {
        const next = [color, ...prev.filter((c) => c !== color)];
        return next.slice(0, MAX_RECENT);
      });
      onChange(color);
      setOpen(false);
    },
    [onChange],
  );

  const handleRecentClick = useCallback(
    (color: string) => (e: React.MouseEvent) => {
      e.preventDefault();
      applyColor(color);
    },
    [applyColor],
  );

  const handlePresetClick = useCallback(
    (color: string) => (e: React.MouseEvent) => {
      e.preventDefault();
      applyColor(color);
    },
    [applyColor],
  );

  // Close popover when clicking outside
  useEffect(() => {
    if (!open) return;
    const handleClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [open]);

  return (
    <div ref={containerRef} className={`inline-flex items-center gap-1.5 ${className}`}>
      <div className="relative">
        <button
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={handleToggle}
          className={`w-7 h-7 flex items-center justify-center rounded-full transition-colors ${
            open
              ? 'text-violet-600 bg-violet-50 dark:bg-violet-900/20 dark:text-violet-300'
              : 'text-slate-500 hover:text-slate-700 hover:bg-slate-100 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-700'
          }`}
          title="选色"
        >
          <Palette className="w-4 h-4" />
        </button>

        {open && (
          <div className="absolute left-0 top-full mt-2.5 z-50 p-3 bg-white dark:bg-slate-800 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-700">
            <div className="grid grid-cols-5 gap-2.5">
              {PRESET_COLORS.map((color) => (
                <button
                  key={color}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={handlePresetClick(color)}
                  className={`w-7 h-7 rounded-full border-2 transition-transform hover:scale-110 ${
                    value === color
                      ? 'border-violet-500 scale-110'
                      : 'border-transparent hover:border-slate-300 dark:hover:border-slate-500'
                  }`}
                  style={{ backgroundColor: color }}
                  title={color}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {recent.map((color) => (
        <button
          key={color}
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={handleRecentClick(color)}
          className={`w-6 h-6 rounded-full border-2 transition-all hover:scale-110 ${
            value === color
              ? 'border-violet-400 scale-110'
              : 'border-slate-300 dark:border-slate-500 hover:border-slate-400'
          }`}
          style={{ backgroundColor: color }}
          title={color}
        />
      ))}
    </div>
  );
}
