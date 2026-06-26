import { useMemo, useState } from 'react';
import { Play, Pause, Loader2, RefreshCw, Mic, Trash2, Info, X } from 'lucide-react';
import RichTextEditor, { type RichTextEditorHandle } from '@/components/RichTextEditor';
import { AuthenticatedImage } from '@/components/AuthenticatedImage';
import ContentBlocksView from '@/pages/note-detail/components/ContentBlocksView';
import { EditableParagraphCards } from '@/pages/note-detail/components/EditableParagraphCards';
import { insertPPTIntoTranscript, deleteAudio, type ContentBlock } from '@/services/api';
import { escapeHtml } from '@/lib/sanitize';
import type { DragState } from './PPTPanel';
import type { useRecording } from '@/pages/note-detail/useRecording';
import type { useTranscript } from '@/pages/note-detail/useTranscript';
import type { useNotes } from '@/pages/note-detail/useNotes';
import type { usePPT } from '@/pages/note-detail/usePPT';
import type { useAudioUpload } from '@/pages/note-detail/hooks/useAudioUpload';
import type { useRestructure } from '@/pages/note-detail/hooks/useRestructure';
import type { useAutoGenerate } from '@/pages/note-detail/hooks/useAutoGenerate';
import type { SessionProcessingStatus } from '@/services/api';
import type { CorrectionStatus } from '@/pages/note-detail/hooks/useRestructure';

interface NotesPanelProps {
  sessionId?: string;
  recording: ReturnType<typeof useRecording>;
  transcript: ReturnType<typeof useTranscript>;
  notesHook: ReturnType<typeof useNotes>;
  ppt: ReturnType<typeof usePPT>;
  audioUpload: ReturnType<typeof useAudioUpload>;
  restructure: ReturnType<typeof useRestructure>;
  processingStatus: SessionProcessingStatus | null;
  autoGen: ReturnType<typeof useAutoGenerate>;
  aiCorrectionStatus: CorrectionStatus;
  setAiCorrectionStatus: React.Dispatch<React.SetStateAction<CorrectionStatus>>;
  transcriptEditRef: React.RefObject<RichTextEditorHandle>;
  paragraphContainerRef: React.RefObject<HTMLDivElement>;
  activeTextElRef: React.MutableRefObject<HTMLDivElement | null>;
  lastSentenceIdxRef: React.MutableRefObject<number>;
  normalizeTranscriptBlockForDisplay: (content?: string) => string;
  onShowLeftPanel: () => void;
  dragState: DragState;
}

export function NotesPanel({
  sessionId,
  recording,
  transcript,
  notesHook,
  ppt,
  audioUpload,
  restructure,
  processingStatus,
  autoGen,
  aiCorrectionStatus,
  setAiCorrectionStatus,
  transcriptEditRef,
  paragraphContainerRef,
  activeTextElRef,
  lastSentenceIdxRef,
  normalizeTranscriptBlockForDisplay,
  onShowLeftPanel,
  dragState,
}: NotesPanelProps) {
  const liveTranscriptHtml = useMemo(() => {
    const confirmed = transcript.state.transcriptText || '';
    const partial = transcript.state.partialText?.trim() || '';
    if (!partial) return confirmed;
    const partialHtml = `<p>${escapeHtml(partial)}</p>`;
    return confirmed ? `${confirmed}${partialHtml}` : partialHtml;
  }, [transcript.state.transcriptText, transcript.state.partialText]);

  const [audioCurrentTimeMs, setAudioCurrentTimeMs] = useState(0);
  const [showCorrectionDetails, setShowCorrectionDetails] = useState(false);

  const isLiveTranscriptMode = recording.state.isRecording || recording.state.isProcessing || audioUpload.state.isUploadingAudio;
  const hasPptImageBlocks = transcript.state.contentBlocks.some((b) => b.type === 'image');

  const handleRestructure = async () => {
    const ok = await restructure.actions.handleRestructure(
      sessionId,
      transcript.actions.receiveAiText,
      setAiCorrectionStatus,
      autoGen.state.autoGenerateStudyMaterials,
    );
    if (!ok || !sessionId || ppt.state.slides.length === 0) return;
    try {
      const result = await insertPPTIntoTranscript(sessionId);
      if (result.blocks?.some((b: ContentBlock) => b.type === 'image')) {
        transcript.actions.updateContentBlocks(result.blocks, false, true);
      }
    } catch {
      /* ignore */
    }
  };

  const renderCorrectionBadge = () => {
    const baseClass = 'px-1.5 py-0.5 rounded text-[10px] font-medium inline-flex items-center gap-1';
    if (aiCorrectionStatus.type === 'corrected') {
      return (
        <button
          type="button"
          onClick={() => setShowCorrectionDetails(true)}
          className={`${baseClass} bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400 hover:bg-green-200 dark:hover:bg-green-900/50`}
          title="DeepSeek AI 已纠正同音字、术语和格式"
        >
          AI 已纠正
          <Info className="w-3 h-3" />
        </button>
      );
    }
    if (aiCorrectionStatus.type === 'processing') {
      return (
        <button
          type="button"
          onClick={() => setShowCorrectionDetails(true)}
          className={`${baseClass} bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 hover:bg-blue-200 dark:hover:bg-blue-900/50`}
          title={aiCorrectionStatus.message || '正在调用 DeepSeek 整理转写'}
        >
          <Loader2 className="w-3 h-3 animate-spin" />
          AI 整理中
          <Info className="w-3 h-3" />
        </button>
      );
    }
    if (aiCorrectionStatus.type === 'local') {
      return (
        <button
          type="button"
          onClick={() => setShowCorrectionDetails(true)}
          className={`${baseClass} bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400 hover:bg-amber-200 dark:hover:bg-amber-900/50`}
          title="未配置 DeepSeek API 或 AI 纠正被拦截，使用本地规则整理"
        >
          本地整理
          <Info className="w-3 h-3" />
        </button>
      );
    }
    if (aiCorrectionStatus.type === 'partial') {
      return (
        <button
          type="button"
          onClick={() => setShowCorrectionDetails(true)}
          className={`${baseClass} bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400 hover:bg-orange-200 dark:hover:bg-orange-900/50`}
          title={aiCorrectionStatus.message || '部分分段使用 AI 整理，失败分段已使用本地稿'}
        >
          AI 部分完成
          <Info className="w-3 h-3" />
        </button>
      );
    }
    if (aiCorrectionStatus.type === 'error') {
      return (
        <button
          type="button"
          onClick={() => setShowCorrectionDetails(true)}
          className={`${baseClass} bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50`}
          title={aiCorrectionStatus.message || 'AI 整理失败'}
        >
          {aiCorrectionStatus.message?.includes('删减')
            ? 'AI 纠正被拦截：疑似删减'
            : aiCorrectionStatus.message?.includes('超时')
              ? 'AI 纠正超时'
              : aiCorrectionStatus.message?.includes('未配置')
                ? '本地整理：未配置 API'
                : 'AI 纠正失败'}
          <Info className="w-3 h-3" />
        </button>
      );
    }
    return null;
  };

  const renderCorrectionDetails = () => {
    if (!showCorrectionDetails) return null;
    const total = aiCorrectionStatus.chunksTotal ?? 0;
    const succeeded = aiCorrectionStatus.chunksSucceeded ?? 0;
    const failed = aiCorrectionStatus.chunksFailed ?? 0;
    const finalSource =
      aiCorrectionStatus.type === 'corrected'
        ? 'AI 整理稿'
        : aiCorrectionStatus.type === 'partial'
          ? 'AI 整理稿 + 本地兜底稿'
          : aiCorrectionStatus.type === 'processing'
            ? '处理中，暂未确定'
            : '本地整理稿';
    const rows = [
      ['当前状态', aiCorrectionStatus.type === 'corrected' ? '已完成' : aiCorrectionStatus.type === 'partial' ? '部分完成' : aiCorrectionStatus.type === 'processing' ? '处理中' : aiCorrectionStatus.type === 'error' ? '失败' : '本地整理'],
      ['最终采用', finalSource],
      ['分段结果', total > 0 ? `共 ${total} 段，成功 ${succeeded} 段，失败 ${failed} 段` : '暂无分段统计'],
      ['错误类型', aiCorrectionStatus.errorType || aiCorrectionStatus.code || '无'],
      ['是否可重试', aiCorrectionStatus.retryable ? '可以重试' : aiCorrectionStatus.type === 'processing' ? '处理中' : '无需重试或不可重试'],
      ['请求 ID', aiCorrectionStatus.requestId || '无'],
    ];

    return (
      <div className="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/30 backdrop-blur-sm px-4">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-2xl">
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-100 dark:border-slate-800">
            <div>
              <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-100">AI 整理详情</h3>
              <p className="mt-0.5 text-xs text-slate-400">用于判断这次最终展示的是 AI 稿还是本地兜底稿。</p>
            </div>
            <button
              type="button"
              onClick={() => setShowCorrectionDetails(false)}
              className="w-8 h-8 rounded-lg flex items-center justify-center text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="px-5 py-4 space-y-3">
            {rows.map(([label, value]) => (
              <div key={label} className="flex items-start justify-between gap-4 text-xs">
                <span className="shrink-0 text-slate-400">{label}</span>
                <span className="text-right text-slate-700 dark:text-slate-200 break-all">{value}</span>
              </div>
            ))}
            {aiCorrectionStatus.message && (
              <div className="rounded-xl bg-slate-50 dark:bg-slate-800/70 px-3 py-2 text-xs text-slate-600 dark:text-slate-300 leading-relaxed">
                {aiCorrectionStatus.message}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };

  return (
    <main className="flex-1 flex flex-col min-h-0 bg-white/40 dark:bg-slate-900/40 backdrop-blur-sm">
      {renderCorrectionDetails()}
      <div className="flex-shrink-0 px-4 md:px-6 py-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300 flex items-center gap-2">
            {recording.state.isRecording ? (
              <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
            ) : (
              <span className="w-2 h-2 rounded-full bg-slate-400" />
            )}
            语音转文字{' '}
            {recording.state.isRecording && <span className="text-xs font-normal text-slate-400">录制中</span>}
            {renderCorrectionBadge()}
          </h2>
          <div className="flex items-center gap-2">
            {transcript.state.transcriptText &&
              !recording.state.isRecording &&
              !audioUpload.state.isUploadingAudio &&
              !recording.state.isProcessing && (
                <button
                  onClick={handleRestructure}
                  disabled={restructure.state.isRestructuring || processingStatus?.overall_status === 'running'}
                  className={`px-2 py-1 text-[10px] font-medium rounded flex items-center gap-1 transition-colors disabled:opacity-50 ${
                    processingStatus?.stages?.transcript_finalize?.status === 'ready' ||
                    processingStatus?.stages?.transcript_finalize?.status === 'fallback'
                      ? 'bg-blue-50 text-blue-600 hover:bg-blue-100 dark:bg-blue-900/20 dark:text-blue-400 dark:hover:bg-blue-900/30'
                      : 'bg-blue-600 text-white hover:bg-blue-700 shadow-sm'
                  }`}
                  title="调用 DeepSeek 整理转写文本并生成学习资料"
                >
                  {restructure.state.isRestructuring ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3 h-3" />
                  )}
                  {processingStatus?.stages?.transcript_finalize?.status === 'ready' ||
                  processingStatus?.stages?.transcript_finalize?.status === 'fallback'
                    ? '重新 AI 整理'
                    : 'AI 整理'}
                </button>
              )}
            {transcript.state.lastSaveTime && (
              <span className="text-xs text-slate-400">
                已保存{' '}
                {new Date(transcript.state.lastSaveTime).toLocaleTimeString('zh-CN', {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </span>
            )}
          </div>
        </div>

        {recording.state.audioPlaybackUrl && !recording.state.isRecording && (
          <div className="mb-3 p-2.5 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl flex items-center gap-3">
            <button
              onClick={() => {
                if (!recording.refs.audioPlayerRef.current) return;
                if (recording.state.isPlayingAudio) {
                  recording.refs.audioPlayerRef.current.pause();
                  recording.actions.setIsPlayingAudio(false);
                } else {
                  recording.refs.audioPlayerRef.current.play();
                  recording.actions.setIsPlayingAudio(true);
                }
              }}
              className="min-w-[44px] min-h-[44px] rounded-full bg-blue-500 text-white flex items-center justify-center hover:bg-blue-600 transition-colors"
            >
              {recording.state.isPlayingAudio ? (
                <Pause className="w-3.5 h-3.5" />
              ) : (
                <Play className="w-3.5 h-3.5 ml-0.5" />
              )}
            </button>
            <span className="text-xs text-blue-600 dark:text-blue-400 flex-1">录音回放</span>
            <button
              onClick={async () => {
                if (!sessionId || !window.confirm('确定要删除录音文件吗？')) return;
                await deleteAudio(sessionId);
              }}
              className="min-w-[44px] min-h-[44px] rounded-lg text-red-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center justify-center transition-colors"
              title="删除录音"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
            <audio
              ref={recording.refs.audioPlayerRef}
              src={recording.state.audioPlaybackUrl}
              onEnded={() => {
                recording.actions.setIsPlayingAudio(false);
                transcript.actions.setActiveSentenceIndex(null);
                lastSentenceIdxRef.current = 0;
              }}
              onPause={() => {
                recording.actions.setIsPlayingAudio(false);
              }}
              onPlay={() => {
                recording.actions.setIsPlayingAudio(true);
                lastSentenceIdxRef.current = 0;
              }}
              onTimeUpdate={(e) => {
                const currentTime = (e.target as HTMLAudioElement).currentTime;
                setAudioCurrentTimeMs(Math.round(currentTime * 1000));
                const sentences = transcript.state.sentencesWithTime;
                if (sentences.length === 0) return;
                let idx = lastSentenceIdxRef.current;
                if (idx >= sentences.length || currentTime < sentences[idx].startTime) {
                  idx = 0;
                }
                for (let i = idx; i < sentences.length; i++) {
                  if (currentTime >= sentences[i].startTime && currentTime < sentences[i].endTime) {
                    lastSentenceIdxRef.current = i;
                    transcript.actions.setActiveSentenceIndex(i);
                    return;
                  }
                }
                if (currentTime >= sentences[sentences.length - 1].startTime) {
                  lastSentenceIdxRef.current = sentences.length - 1;
                  transcript.actions.setActiveSentenceIndex(sentences.length - 1);
                }
              }}
              className="hidden"
            />
          </div>
        )}
      </div>

      {/* 转写内容滚动区域 */}
      <div className="flex-1 overflow-y-auto px-4 md:px-6 pb-4">
        {isLiveTranscriptMode ? (
          <div className="space-y-3">
            <RichTextEditor
              ref={transcriptEditRef}
              value={liveTranscriptHtml}
              onChange={(text) => {
                transcript.actions.markUserEdited();
                transcript.actions.updateTranscriptDraft(text);
                transcript.actions.clearPartialText();
              }}
              onFocus={() => {
                transcript.actions.setEditorFocused(true);
                activeTextElRef.current = transcriptEditRef.current?.getRootElement() ?? null;
              }}
              onBlur={() => {
                transcript.actions.setEditorFocused(false);
                transcript.actions.commitTranscriptDraft();
                transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, false);
              }}
              placeholder={
                audioUpload.state.isUploadingAudio
                  ? '正在识别上传录音，结果会逐段显示...'
                  : '正在转录中，可直接编辑修改...'
              }
              className="rich-text-editor w-full p-4 text-sm text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-800 border border-blue-200 dark:border-blue-700 rounded-xl min-h-[200px] focus:outline-none focus:ring-2 focus:ring-blue-200 leading-relaxed whitespace-pre-wrap break-words"
            />
            {recording.state.isRecording && !recording.state.isPaused && (
              <div className="flex items-center gap-2 px-3 py-2 text-slate-400 text-sm">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                {transcript.state.partialText ? '实时识别中…' : '正在聆听…'}
              </div>
            )}
            {(recording.state.isProcessing || audioUpload.state.isUploadingAudio) && (
              <div className="flex items-center gap-2 text-slate-400 text-sm">
                <Loader2 className="w-4 h-4 animate-spin" />
                {audioUpload.state.isUploadingAudio
                  ? audioUpload.state.audioUploadStatus || '正在识别上传录音...'
                  : '正在处理录音...'}
              </div>
            )}
            {recording.state.isRecording &&
              transcript.state.contentBlocks.some((b) => b.type === 'image') && (
                <div className="space-y-2">
                  <p className="text-xs text-slate-500 dark:text-slate-400">已匹配 PPT：</p>
                  <div className="flex flex-wrap gap-2">
                    {transcript.state.contentBlocks
                      .filter(
                        (b): b is ContentBlock & { type: 'image'; src: string; page?: number } =>
                          b.type === 'image' && !!b.src,
                      )
                      .map((block, idx) => (
                        <button
                          key={`live-slide-${block.page ?? idx}-${idx}`}
                          onClick={() => {
                            const slideIndex = ppt.state.slides.findIndex((s) => s.page === block.page);
                            if (slideIndex >= 0) ppt.actions.setActiveSlideIndex(slideIndex);
                          }}
                          className="relative w-20 h-14 rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700 hover:ring-2 hover:ring-blue-200 transition-all"
                          title={`PPT 第 ${block.page} 页`}
                        >
                          <AuthenticatedImage
                            src={block.src}
                            alt={`PPT ${block.page}`}
                            className="w-full h-full object-cover"
                            fallback={<div className="w-full h-full bg-slate-100 dark:bg-slate-800" />}
                          />
                          {block.page && (
                            <span className="absolute bottom-0.5 right-0.5 px-1 py-0.5 text-[10px] bg-black/50 text-white rounded">
                              {block.page}
                            </span>
                          )}
                        </button>
                      ))}
                  </div>
                </div>
              )}
          </div>
        ) : hasPptImageBlocks ||
          (transcript.state.contentBlocks.length > 0 &&
            transcript.state.contentBlocks.some((b) => b.type === 'image')) ? (
          <ContentBlocksView
            blocks={transcript.state.contentBlocks}
            slides={ppt.state.slides}
            onSetActiveSlideIndex={(idx) => ppt.actions.setActiveSlideIndex(idx)}
            onShowLeftPanel={onShowLeftPanel}
            onUpdateContentBlocks={(blocks) => {
              transcript.actions.updateContentBlocks(blocks);
              transcript.actions.scheduleSave(() => notesHook.refs.notesDraftRef.current, 300);
            }}
            onUpdateBlockDraft={transcript.actions.updateContentBlockDraft}
            onCommitContentBlocks={() => {
              transcript.actions.commitContentBlockDraft();
              transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, false);
            }}
            normalizeTranscriptBlockForDisplay={normalizeTranscriptBlockForDisplay}
            activeTextElRef={activeTextElRef}
            dropTargetIndex={dragState.targetIndex}
            dropPosition={dragState.targetPosition}
          />
        ) : transcript.state.transcriptText === '' ? (
          <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500">
            <div className="w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
              {audioUpload.state.isUploadingAudio ? (
                <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
              ) : (
                <Mic className="w-6 h-6 text-slate-300 dark:text-slate-600" />
              )}
            </div>
            <p className="text-sm">
              {audioUpload.state.isUploadingAudio ? '正在等待第一段转写' : '点击录制按钮开始录音'}
            </p>
            <p className="text-xs mt-1 text-slate-300 dark:text-slate-600">
              {audioUpload.state.isUploadingAudio
                ? '识别结果会先显示原文，再由 AI 替换为整理稿'
                : '录音将实时转写，PPT 自动对齐插入'}
            </p>
          </div>
        ) : transcript.state.transcriptText ? (
          <EditableParagraphCards
            transcriptText={transcript.state.transcriptText}
            containerRef={paragraphContainerRef}
            paragraphTimeRanges={
              recording.state.audioPlaybackUrl ? transcript.state.paragraphTimeRanges : []
            }
            currentTimeMs={audioCurrentTimeMs}
            onSeek={(ms) => {
              const audio = recording.refs.audioPlayerRef.current;
              if (!audio) return;
              audio.currentTime = ms / 1000;
              audio.play().catch(() => { /* ignore autoplay errors */ });
              recording.actions.setIsPlayingAudio(true);
            }}
            onUpdateDraft={transcript.actions.updateTranscriptDraft}
            onCommitDraft={() => {
              transcript.actions.commitTranscriptDraft();
              transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, false);
            }}
            onMarkUserEdited={transcript.actions.markUserEdited}
            onSetActiveTextEl={(el) => {
              activeTextElRef.current = el;
            }}
            onClearSentences={() => {
              if (transcript.state.sentencesWithTime.length > 0) {
                transcript.actions.setSentencesWithTime([]);
                transcript.actions.setActiveSentenceIndex(null);
              }
            }}
          />
        ) : transcript.state.sentencesWithTime.length > 0 ? (
          <div className="space-y-1 leading-relaxed whitespace-pre-wrap break-words">
            {transcript.state.sentencesWithTime.map((sentence, idx) => {
              const hasAudio = !!recording.state.audioPlaybackUrl;
              return (
                <span
                  key={idx}
                  onClick={
                    hasAudio
                      ? () => {
                          if (recording.refs.audioPlayerRef.current) {
                            recording.refs.audioPlayerRef.current.currentTime = sentence.startTime;
                            recording.refs.audioPlayerRef.current.play();
                            recording.actions.setIsPlayingAudio(true);
                          }
                        }
                      : undefined
                  }
                  className={`inline px-0.5 py-0.5 rounded transition-colors ${
                    transcript.state.activeSentenceIndex === idx
                      ? 'bg-blue-200 dark:bg-blue-700 text-blue-900 dark:text-blue-100'
                      : hasAudio
                        ? 'cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700'
                        : ''
                  }`}
                >
                  {sentence.text}
                </span>
              );
            })}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500">
            <div className="w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
              <Mic className="w-6 h-6 text-slate-300 dark:text-slate-600" />
            </div>
            <p className="text-sm">转录内容将显示在这里</p>
          </div>
        )}
      </div>
    </main>
  );
}
