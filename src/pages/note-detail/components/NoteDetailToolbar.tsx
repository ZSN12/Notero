import { Play, Pause, Square, Loader2, AlertCircle, ImagePlus, Mic, MicOff, Bold, List } from 'lucide-react';
import type { usePPT } from '@/pages/note-detail/usePPT';
import type { useRecording } from '@/pages/note-detail/useRecording';
import type { useTranscript } from '@/pages/note-detail/useTranscript';
import type { useAudioUpload } from '@/pages/note-detail/hooks/useAudioUpload';
import type { CorrectionStatus } from '@/pages/note-detail/hooks/useRestructure';

const TEXT_COLORS = [
  { name: '红色', value: '#ef4444' },
  { name: '黄色', value: '#eab308' },
  { name: '蓝色', value: '#3b82f6' },
  { name: '黑色', value: '#1e293b' },
];

interface NoteDetailToolbarProps {
  fileInputRef: React.RefObject<HTMLInputElement>;
  onPPTClick: () => void;
  onPPTSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onStopRecording: () => void;
  activeTextElRef: React.MutableRefObject<HTMLDivElement | null>;
  paragraphContainerRef: React.RefObject<HTMLDivElement>;
  ppt: ReturnType<typeof usePPT>;
  recording: ReturnType<typeof useRecording>;
  transcript: ReturnType<typeof useTranscript>;
  audioUpload: ReturnType<typeof useAudioUpload>;
  setAiCorrectionStatus: React.Dispatch<React.SetStateAction<CorrectionStatus>>;
}

export function NoteDetailToolbar({
  fileInputRef,
  onPPTClick,
  onPPTSelect,
  onStopRecording,
  activeTextElRef,
  paragraphContainerRef,
  ppt,
  recording,
  transcript,
  audioUpload,
  setAiCorrectionStatus,
}: NoteDetailToolbarProps) {
  const applyFormat = (formatType: string, value?: string) => {
    const el = activeTextElRef.current;
    if (!el) return;
    el.focus();
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    const range = sel.getRangeAt(0);
    if (range.collapsed) return;
    const selectedText = range.toString();
    if (!selectedText) return;

    const findAncestor = (node: Node, tag: string, predicate?: (e: HTMLElement) => boolean): HTMLElement | null => {
      let cur: Node | null = node;
      while (cur && cur !== el) {
        if (cur.nodeType === Node.ELEMENT_NODE) {
          const elem = cur as HTMLElement;
          if (elem.tagName.toLowerCase() === tag && (!predicate || predicate(elem))) {
            return elem;
          }
        }
        cur = cur.parentNode;
      }
      return null;
    };

    const unwrap = (wrapper: HTMLElement) => {
      const parent = wrapper.parentNode;
      if (!parent) return;
      while (wrapper.firstChild) {
        parent.insertBefore(wrapper.firstChild, wrapper);
      }
      parent.removeChild(wrapper);
    };

    switch (formatType) {
      case 'bold': {
        const strong = findAncestor(range.startContainer, 'strong');
        if (strong && strong.contains(range.endContainer)) {
          unwrap(strong);
        } else {
          const wrapper = document.createElement('strong');
          try {
            range.surroundContents(wrapper);
          } catch {
            const fragment = range.extractContents();
            wrapper.appendChild(fragment);
            range.insertNode(wrapper);
          }
        }
        break;
      }
      case 'insertUnorderedList': {
        const ul = document.createElement('ul');
        const li = document.createElement('li');
        li.textContent = selectedText;
        ul.appendChild(li);
        range.deleteContents();
        range.insertNode(ul);
        break;
      }
      case 'foreColor': {
        if (value) {
          const sameColorSpan = findAncestor(range.startContainer, 'span', (s) => s.style.color === value);
          if (sameColorSpan && sameColorSpan.contains(range.endContainer)) {
            unwrap(sameColorSpan);
          } else {
            const span = document.createElement('span');
            span.style.color = value;
            try {
              range.surroundContents(span);
            } catch {
              const fragment = range.extractContents();
              span.appendChild(fragment);
              range.insertNode(span);
            }
          }
        }
        break;
      }
    }
    sel.removeAllRanges();
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };

  const handleAudioUploadClick = () => {
    if (audioUpload.refs.audioInputRef.current) {
      audioUpload.refs.audioInputRef.current.value = '';
    }
    audioUpload.refs.audioInputRef.current?.click();
  };

  const handleAudioSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    audioUpload.actions.handleAudioUpload(Array.from(files), {
      clearDerivedTranscriptViews: transcript.actions.clearDerivedTranscriptViews,
      clearStreamingTranscriptChunks: transcript.actions.clearStreamingTranscriptChunks,
      updateTranscriptText: transcript.actions.updateTranscriptText,
      appendTranscriptText: transcript.actions.appendTranscriptText,
      receiveAiText: transcript.actions.receiveAiText,
      clearStreamingTranscriptChunksFinal: transcript.actions.clearStreamingTranscriptChunks,
      clearContentBlocks: transcript.actions.clearContentBlocks,
      scrollToBottom: () => {
        if (paragraphContainerRef.current) {
          paragraphContainerRef.current.scrollTop = paragraphContainerRef.current.scrollHeight;
        }
      },
    }, setAiCorrectionStatus);
  };

  return (
    <div className="flex-shrink-0 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border-b border-slate-200/60 dark:border-slate-700/60">
      <div className="px-3 py-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            type="file"
            accept=".ppt,.pptx,.pdf"
            onChange={onPPTSelect}
            className="hidden"
          />
          <button
            onClick={onPPTClick}
            disabled={ppt.state.isUploadingPPT}
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg hover:border-blue-300 hover:text-blue-600 transition-all disabled:opacity-50"
          >
            {ppt.state.isUploadingPPT ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <ImagePlus className="w-3.5 h-3.5" />
            )}
            {ppt.state.isUploadingPPT ? '上传中...' : '上传PPT'}
          </button>
          {ppt.state.slides.length > 0 && <span className="text-xs text-slate-400">{ppt.state.slides.length} 页</span>}

          <input
            ref={audioUpload.refs.audioInputRef}
            type="file"
            multiple
            accept=".wav,.mp3,.webm,.m4a,.ogg,.flac"
            onChange={handleAudioSelect}
            className="hidden"
          />
          <button
            onClick={handleAudioUploadClick}
            disabled={audioUpload.state.isUploadingAudio}
            className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg hover:border-green-300 hover:text-green-600 transition-all disabled:opacity-50"
          >
            {audioUpload.state.isUploadingAudio ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Mic className="w-3.5 h-3.5" />
            )}
            {audioUpload.state.isUploadingAudio
              ? audioUpload.state.audioQueueProgress
                ? `处理中 ${audioUpload.state.audioQueueProgress.current}/${audioUpload.state.audioQueueProgress.total}`
                : '处理中...'
              : '上传录音'}
          </button>
        </div>

        <div className="flex items-center gap-3">
          <div className="relative">
            {recording.state.isProcessing ? (
              <button
                disabled
                className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-500 to-blue-600 text-white flex items-center justify-center shadow-lg cursor-wait"
              >
                <Loader2 className="w-4 h-4 animate-spin" />
              </button>
            ) : recording.state.isError ? (
              <button
                onClick={() => {
                  if (recording.state.isRecording) {
                    recording.actions.stopRecording(transcript.actions.receiveAiText);
                  }
                }}
                className="w-9 h-9 rounded-full bg-gradient-to-br from-red-500 to-red-600 text-white flex items-center justify-center shadow-lg hover:shadow-xl transition-all hover:scale-105 active:scale-95"
              >
                <AlertCircle className="w-4 h-4" />
              </button>
            ) : (
              <button
                onClick={() => {
                  if (recording.state.isPaused) recording.actions.resumeRecording();
                  else if (recording.state.isRecording) recording.actions.pauseRecording();
                  else {
                    transcript.actions.clearDerivedTranscriptViews();
                    transcript.actions.clearStreamingState();
                    recording.actions.startRecording(
                      transcript.actions.receivePartial,
                      transcript.actions.receiveFinal,
                    );
                  }
                }}
                className={`w-11 h-11 rounded-full text-white flex items-center justify-center shadow-lg hover:shadow-xl transition-all hover:scale-105 active:scale-95 ${
                  recording.state.isRecording
                    ? 'bg-gradient-to-br from-amber-500 to-amber-600 shadow-amber-200'
                    : 'bg-gradient-to-br from-blue-500 to-blue-600 shadow-blue-200'
                }`}
              >
                {recording.state.isRecording ? (
                  <Pause className="w-4 h-4" />
                ) : (
                  <Play className="w-4 h-4 ml-0.5" />
                )}
              </button>
            )}
          </div>

          <div className="flex items-center gap-0.5 h-7 hidden sm:flex">
            {recording.state.waveHeights.map((height, i) => (
              <div
                key={i}
                className="w-1 rounded-full transition-all duration-75"
                style={{
                  height: `${height}px`,
                  backgroundColor: recording.state.isRecording ? 'rgba(59, 130, 246, 0.5)' : 'rgba(148, 163, 184, 0.3)',
                }}
              />
            ))}
          </div>

          <span className="text-sm font-mono font-medium text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-700 px-2.5 py-0.5 rounded-md tabular-nums">
            {recording.state.currentTime}
          </span>

          {recording.state.isRecording && (
            <button
              onClick={() => {
                if (recording.state.isPaused) recording.actions.resumeRecording();
                else recording.actions.pauseRecording();
              }}
              className="flex items-center gap-1 px-3 py-2 text-sm font-medium rounded-md bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 hover:bg-amber-200 transition-colors min-h-[44px]"
            >
              {recording.state.isPaused ? <Play className="w-3 h-3" /> : <Square className="w-3 h-3" />}
              {recording.state.isPaused ? '继续' : '暂停'}
            </button>
          )}

          {recording.state.isRecording && (
            <button
              onClick={onStopRecording}
              className="flex items-center gap-1 px-3 py-2 text-sm font-medium rounded-md bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors min-h-[44px]"
            >
              <MicOff className="w-3.5 h-3.5" />
              停止
            </button>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          <button
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => applyFormat('bold')}
            className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
            title="加粗"
          >
            <Bold className="w-5 h-5" />
          </button>
          <button
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => applyFormat('insertUnorderedList')}
            className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
            title="列表"
          >
            <List className="w-5 h-5" />
          </button>
          <div className="w-px h-5 bg-slate-200 dark:bg-slate-600 mx-1" />
          <div className="flex items-center gap-1.5">
            {TEXT_COLORS.map((color) => (
              <button
                key={color.value}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => applyFormat('foreColor', color.value)}
                className="w-7 h-7 rounded-full border-2 border-slate-300 dark:border-slate-500 hover:scale-125 hover:border-slate-400 transition-all"
                style={{ backgroundColor: color.value }}
                title={color.name}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
