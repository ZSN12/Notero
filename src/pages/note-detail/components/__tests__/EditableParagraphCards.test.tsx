import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EditableParagraphCards } from '../../index';

describe('EditableParagraphCards deletion', () => {
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
      />
    );

    const block = screen.getByText('Hello world');
    block.focus();
    block.innerHTML = '';
    fireEvent.input(block);

    expect(onUpdateDraft).toHaveBeenCalledWith('');
  });

  it('reflects partial deletion in a multi-paragraph transcript', () => {
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
      />
    );

    const block = screen.getByText('Paragraph one.');
    block.focus();
    block.innerHTML = 'Paragraph';
    fireEvent.input(block);

    expect(onUpdateDraft).toHaveBeenCalledWith('Paragraph\n\nParagraph two.');
  });
});
