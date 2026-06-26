import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { createRef } from 'react';
import { EditableParagraphCards } from '../EditableParagraphCards';
import type { EditableParagraphCardsHandle } from '../EditableParagraphCards';
import { stableTextId } from '@/lib/sourceAnchors';

describe('EditableParagraphCards', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('calls onUpdateDraft with empty string when all text is deleted', () => {
    const onUpdateDraft = vi.fn();
    render(
      <EditableParagraphCards
        transcriptText="Hello world"
        onUpdateDraft={onUpdateDraft}
        onCommitDraft={vi.fn()}
        onMarkUserEdited={vi.fn()}
        onSetActiveTextEl={vi.fn()}
        onClearSentences={vi.fn()}
      />,
    );

    const block = screen.getByText('Hello world');
    block.focus();
    block.innerHTML = '';
    fireEvent.input(block);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(onUpdateDraft).toHaveBeenLastCalledWith('');
  });

  it('reflects partial deletion after the debounced commit', () => {
    const onUpdateDraft = vi.fn();
    const text = 'Paragraph one.\n\nParagraph two.';
    render(
      <EditableParagraphCards
        transcriptText={text}
        onUpdateDraft={onUpdateDraft}
        onCommitDraft={vi.fn()}
        onMarkUserEdited={vi.fn()}
        onSetActiveTextEl={vi.fn()}
        onClearSentences={vi.fn()}
      />,
    );

    const block = screen.getByText('Paragraph one.');
    block.focus();
    block.innerHTML = 'Paragraph';
    fireEvent.input(block);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(onUpdateDraft).toHaveBeenLastCalledWith('Paragraph\n\nParagraph two.');
  });

  it('undoes and redoes the last edit via the imperative handle', () => {
    const onUpdateDraft = vi.fn();
    const ref = createRef<EditableParagraphCardsHandle>();
    render(
      <EditableParagraphCards
        ref={ref}
        transcriptText="Hello world"
        onUpdateDraft={onUpdateDraft}
        onCommitDraft={vi.fn()}
        onMarkUserEdited={vi.fn()}
        onSetActiveTextEl={vi.fn()}
        onClearSentences={vi.fn()}
      />,
    );

    const block = screen.getByText('Hello world');
    block.focus();
    block.innerHTML = 'Hello';
    fireEvent.input(block);

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(onUpdateDraft).toHaveBeenLastCalledWith('Hello');

    act(() => {
      ref.current?.undo();
    });

    expect(onUpdateDraft).toHaveBeenLastCalledWith('Hello world');
    expect(screen.getByText('Hello world')).toBeInTheDocument();

    act(() => {
      ref.current?.redo();
    });

    expect(onUpdateDraft).toHaveBeenLastCalledWith('Hello');
    expect(screen.getByText('Hello')).toBeInTheDocument();
  });

  it('shows a timestamp badge when paragraphTimeRanges are provided', () => {
    render(
      <EditableParagraphCards
        transcriptText={'First paragraph.\n\nSecond paragraph.'}
        paragraphTimeRanges={[
          { text: 'First paragraph.', start_ms: 1000, end_ms: 5000 },
          { text: 'Second paragraph.', start_ms: 5000, end_ms: 9000 },
        ]}
        onUpdateDraft={vi.fn()}
        onCommitDraft={vi.fn()}
        onMarkUserEdited={vi.fn()}
        onSetActiveTextEl={vi.fn()}
        onClearSentences={vi.fn()}
      />,
    );

    expect(screen.getAllByTitle('跳转到该段落').length).toBe(2);
    expect(screen.getByText('00:00:01')).toBeInTheDocument();
  });

  it('highlights the paragraph matching the current playback time', () => {
    const transcriptText = 'First paragraph.\n\nSecond paragraph.';
    const paragraphTimeRanges = [
      { text: 'First paragraph.', start_ms: 1000, end_ms: 5000 },
      { text: 'Second paragraph.', start_ms: 5000, end_ms: 9000 },
    ];
    const { rerender } = render(
      <EditableParagraphCards
        transcriptText={transcriptText}
        paragraphTimeRanges={paragraphTimeRanges}
        currentTimeMs={3000}
        onUpdateDraft={vi.fn()}
        onCommitDraft={vi.fn()}
        onMarkUserEdited={vi.fn()}
        onSetActiveTextEl={vi.fn()}
        onClearSentences={vi.fn()}
      />,
    );

    const blocks = screen.getAllByText(/paragraph/i);
    expect(blocks[0].className).toContain('bg-blue-50');
    expect(blocks[1].className).not.toContain('bg-blue-50');

    rerender(
      <EditableParagraphCards
        transcriptText={transcriptText}
        paragraphTimeRanges={paragraphTimeRanges}
        currentTimeMs={6000}
        onUpdateDraft={vi.fn()}
        onCommitDraft={vi.fn()}
        onMarkUserEdited={vi.fn()}
        onSetActiveTextEl={vi.fn()}
        onClearSentences={vi.fn()}
      />,
    );

    expect(blocks[0].className).not.toContain('bg-blue-50');
    expect(blocks[1].className).toContain('bg-blue-50');
  });

  it('calls onSeek when a timestamp badge is clicked', () => {
    const onSeek = vi.fn();
    render(
      <EditableParagraphCards
        transcriptText="First paragraph."
        paragraphTimeRanges={[{ text: 'First paragraph.', start_ms: 2500, end_ms: 5000 }]}
        onSeek={onSeek}
        onUpdateDraft={vi.fn()}
        onCommitDraft={vi.fn()}
        onMarkUserEdited={vi.fn()}
        onSetActiveTextEl={vi.fn()}
        onClearSentences={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTitle('跳转到该段落'));
    expect(onSeek).toHaveBeenCalledWith(2500);
  });

  it('adds stable paragraph anchors for RAG source jumps', () => {
    render(
      <EditableParagraphCards
        transcriptText={`First paragraph.

Second paragraph.`}
        onUpdateDraft={vi.fn()}
        onCommitDraft={vi.fn()}
        onMarkUserEdited={vi.fn()}
        onSetActiveTextEl={vi.fn()}
        onClearSentences={vi.fn()}
      />,
    );

    expect(screen.getByText('First paragraph.')).toHaveAttribute(
      'data-paragraph-id',
      stableTextId('transcript', 0, 'First paragraph.'),
    );
    expect(screen.getByText('Second paragraph.')).toHaveAttribute(
      'data-paragraph-id',
      stableTextId('transcript', 1, 'Second paragraph.'),
    );
  });
});
