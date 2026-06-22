import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ColorPicker } from '../ColorPicker';

const STORAGE_KEY = 'nootbook-recent-colors';

describe('ColorPicker', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('renders palette button and two default recent colors', () => {
    render(<ColorPicker onChange={vi.fn()} />);
    expect(screen.getByTitle('选色')).toBeInTheDocument();
    expect(screen.getByTitle('#ef4444')).toBeInTheDocument();
    expect(screen.getByTitle('#3b82f6')).toBeInTheDocument();
  });

  it('calls onChange when a recent color is clicked', () => {
    const onChange = vi.fn();
    render(<ColorPicker onChange={onChange} />);

    fireEvent.click(screen.getByTitle('#ef4444'));
    expect(onChange).toHaveBeenCalledWith('#ef4444');
  });

  it('updates recent colors and localStorage when a preset color is picked', () => {
    const onChange = vi.fn();
    render(<ColorPicker onChange={onChange} />);

    fireEvent.click(screen.getByTitle('选色'));
    fireEvent.click(screen.getByTitle('#10b981'));

    expect(onChange).toHaveBeenCalledWith('#10b981');
    expect(screen.getByTitle('#10b981')).toBeInTheDocument();
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')).toEqual(['#10b981', '#ef4444']);
  });

  it('moves an already-recent color to the front without duplicating', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['#111111', '#222222']));
    const onChange = vi.fn();
    render(<ColorPicker onChange={onChange} />);

    fireEvent.click(screen.getByTitle('#222222'));
    expect(onChange).toHaveBeenCalledWith('#222222');

    fireEvent.click(screen.getByTitle('#222222'));

    expect(JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]')).toEqual(['#222222', '#111111']);
  });

  it('reads initial recent colors from localStorage', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(['#abcdef', '#123456']));
    render(<ColorPicker onChange={vi.fn()} />);

    expect(screen.getByTitle('#abcdef')).toBeInTheDocument();
    expect(screen.getByTitle('#123456')).toBeInTheDocument();
  });

  it('highlights the current value', () => {
    const { container } = render(<ColorPicker value="#ef4444" onChange={vi.fn()} />);
    const active = container.querySelector('.border-violet-400');
    expect(active).toBeInTheDocument();
  });
});
