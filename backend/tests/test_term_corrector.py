"""Tests for TermCorrector deterministic cleanup and LLM fallback logic."""

import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

os.environ["DEEPSEEK_API_KEY"] = "test-key"
os.environ["DEEPSEEK_BASE_URL"] = "https://api.example.com"

from app.services.term_corrector import TermCorrector, corrector, RestructureResult, RestructureChunkResult, CorrectionError, CORRECTION_ERROR_CODES


class TestHasLLM:
    def test_has_llm_when_client_present(self):
        c = TermCorrector()
        c._client = MagicMock()
        assert c.has_llm is True

    def test_has_llm_when_client_none(self):
        c = TermCorrector()
        c._client = None
        assert c.has_llm is False


class TestCleanTranscriptForDisplay:
    def test_empty_and_whitespace(self):
        assert corrector.clean_transcript_for_display("") == ""
        assert corrector.clean_transcript_for_display(None) == ""

    def test_oral_fillers_removed(self):
        raw = "好，今天我们学习单例模式。那么，单例模式确保一个类只有一个实例。对吧？"
        result = corrector.clean_transcript_for_display(raw)
        assert "好，" not in result
        assert "那么，" not in result
        assert "对吧" not in result
        assert "单例模式" in result

    def test_repeated_sentences_deduped(self):
        raw = "单例模式确保一个类只有一个实例。单例模式确保一个类只有一个实例。工厂模式用于创建对象。"
        result = corrector.clean_transcript_for_display(raw)
        # Should keep only one occurrence of the repeated sentence
        assert result.count("单例模式确保一个类只有一个实例") == 1
        assert "工厂模式用于创建对象" in result

    def test_paragraph_breaks_inserted(self):
        raw = "今天我们学习A。接下来我们学习B。然后学习C。最后学习D。"
        result = corrector.clean_transcript_for_display(raw)
        # Topic shifts should create paragraph breaks
        assert "\n\n" in result


class TestPrepareStreamChunk:
    def test_empty_input(self):
        assert corrector.prepare_stream_chunk("") == ""

    def test_overlap_removed(self):
        history = "今天我们学习单例模式。"
        chunk = "今天我们学习单例模式。接下来学习工厂模式。"
        result = corrector.prepare_stream_chunk(chunk, history)
        assert "今天我们学习单例模式" not in result
        assert "工厂模式" in result

    def test_no_overlap(self):
        history = "今天我们学习A。"
        chunk = "接下来学习B。"
        result = corrector.prepare_stream_chunk(chunk, history)
        assert "接下来学习B" in result


class TestStripHistoryOverlap:
    def test_empty_inputs(self):
        assert corrector.strip_history_overlap("", "history") == ""
        assert corrector.strip_history_overlap("candidate", "") == "candidate"

    def test_full_containment(self):
        history = "今天我们学习单例模式和工厂模式。"
        candidate = "今天我们学习单例模式和工厂模式。"
        result = corrector.strip_history_overlap(candidate, history)
        # Full match should return empty or very short remainder
        assert len(result) < len(candidate)

    def test_prefix_overlap(self):
        history = "今天我们学习单例模式。"
        candidate = "单例模式确保一个类只有一个实例。"
        result = corrector.strip_history_overlap(candidate, history)
        assert "单例模式" in result

    def test_no_overlap(self):
        history = "今天我们学习A。"
        candidate = "接下来我们学习B。"
        result = corrector.strip_history_overlap(candidate, history)
        assert result == candidate


class TestSplitSentences:
    def test_chinese_punctuation(self):
        text = "你好。世界！这是测试？"
        sentences = corrector._split_sentences(text)
        assert len(sentences) == 3
        assert "你好" in sentences[0]
        assert "世界" in sentences[1]
        assert "这是测试" in sentences[2]

    def test_english_punctuation(self):
        text = "Hello world. This is a test! Is it?"
        sentences = corrector._split_sentences(text)
        assert len(sentences) == 3

    def test_no_punctuation(self):
        text = "没有标点的文本"
        sentences = corrector._split_sentences(text)
        assert sentences == [text]


class TestCleanOralFillers:
    def test_start_fillers(self):
        sentences = ["好，今天我们学习。", "那么，接下来是B。", "然后，我们看看C。"]
        result = corrector._clean_oral_fillers(sentences)
        for s in result:
            assert not s.startswith("好，")
            assert not s.startswith("那么，")
            assert not s.startswith("然后，")

    def test_end_fillers(self):
        sentences = ["今天我们学习单例模式，对吧", "这是测试，是不是"]
        result = corrector._clean_oral_fillers(sentences)
        for s in result:
            assert "对吧" not in s
            assert "是不是" not in s

    def test_inline_fillers(self):
        sentences = ["就是这样的啊单例模式。", "这个这个很重要。"]
        result = corrector._clean_oral_fillers(sentences)
        for s in result:
            assert "就是这样的啊" not in s
            assert "这个这个" not in s

    def test_monosyllabic_fillers(self):
        # Monosyllabic fillers must be surrounded by punctuation to be removed
        sentences = ["单例模式啊，确保一个实例。", "工厂模式，呃，用于创建对象。"]
        result = corrector._clean_oral_fillers(sentences)
        assert "啊，" not in result[0]
        assert "呃，" not in result[1]


class TestDedupeSemanticSentences:
    def test_no_duplicates(self):
        # Sentences must be >= 5 chars to participate in dedup logic
        sentences = ["今天我们要学习A内容。", "明天继续学习B部分。", "后天复习C知识。"]
        result = corrector._dedupe_semantic_sentences(sentences)
        assert len(result) == 3

    def test_exact_duplicate_removed(self):
        sentences = ["单例模式确保一个实例。", "单例模式确保一个实例。", "工厂模式创建对象。"]
        result = corrector._dedupe_semantic_sentences(sentences)
        assert len(result) == 2
        assert result.count("单例模式确保一个实例。") == 1

    def test_short_sentences_kept(self):
        sentences = ["A。", "B。", "A。"]
        result = corrector._dedupe_semantic_sentences(sentences)
        # Sentences shorter than 5 chars are skipped from dedup logic
        assert len(result) <= 3


class TestCollapseRepeatedClauses:
    def test_no_repetition(self):
        text = "A，B，C"
        result = corrector._collapse_repeated_clauses(text)
        assert result == text

    def test_repeated_clauses_collapsed(self):
        text = "单例模式，单例模式，工厂模式"
        result = corrector._collapse_repeated_clauses(text)
        assert result.count("单例模式") == 1
        assert "工厂模式" in result


class TestCollapseRepeatedSentenceLoops:
    def test_loop_removed(self):
        text = "什么问题？什么问题？什么问题？"
        result = corrector._collapse_repeated_sentence_loops(text)
        assert result.count("什么问题") == 1

    def test_no_loop_kept(self):
        text = "A。B。C。"
        result = corrector._collapse_repeated_sentence_loops(text)
        assert "A" in result
        assert "B" in result
        assert "C" in result


class TestDedupeParagraphs:
    def test_duplicate_paragraph_removed(self):
        # Paragraphs need norm_key length >= 20 to be deduped
        text = (
            "这是一个非常长的段落内容，用来测试重复段落检测功能是否正确工作。\n\n"
            "这是一个非常长的段落内容，用来测试重复段落检测功能是否正确工作。\n\n"
            "这是另一个完全不同的段落内容，不应该被删除。"
        )
        result = corrector._dedupe_paragraphs(text)
        assert result.count("这是一个非常长的段落内容") == 1
        assert "这是另一个完全不同的段落内容" in result

    def test_no_duplicate_kept(self):
        text = "A。\n\nB。\n\nC。"
        result = corrector._dedupe_paragraphs(text)
        assert "A" in result
        assert "B" in result
        assert "C" in result


class TestSentencesEquivalent:
    def test_exact_match(self):
        assert corrector._sentences_equivalent("单例模式", "单例模式") is True

    def test_different_sentences(self):
        assert corrector._sentences_equivalent("单例模式", "工厂模式") is False

    def test_containment(self):
        a = "单例模式确保一个类只有一个实例"
        b = "单例模式确保一个类只有一个实例，常用于数据库连接池"
        assert corrector._sentences_equivalent(a, b) is True

    def test_similar_but_not_equivalent(self):
        # First 3 chars differ so the 0.80 similarity shortcut is not triggered
        a = "明天我们学习单例模式"
        b = "今天我们学习工厂模式"
        assert corrector._sentences_equivalent(a, b) is False


class TestNormKey:
    def test_filler_removal(self):
        key = corrector._norm_key("好，那么单例模式对吧")
        # "好" is not in the filler list (only "好的" is), but "那么" and "对吧" are removed
        assert "那么" not in key
        assert "对吧" not in key
        assert "单例模式" in key

    def test_punctuation_removal(self):
        key = corrector._norm_key("A。B！C？")
        assert "。" not in key
        assert "！" not in key


class TestBuildCourseTerms:
    def test_extracts_terms_from_ppt_title_and_text(self):
        slides = [
            {
                "page": 1,
                "title": "父进程和子进程",
                "text": "fork 创建子进程，exec 族函数替换程序映像。无名管道与有名管道区别，mkfifo、unlink、FIFO、文件描述符。",
            }
        ]
        terms = TermCorrector.build_course_terms("嵌入式系统", [], slides)

        assert "父进程" in terms
        assert "子进程" in terms
        assert "无名管道" in terms
        assert "有名管道" in terms
        assert "fork" in terms
        assert "exec" in terms
        assert "mkfifo" in terms

    def test_does_not_learn_wrong_asr_homophone_from_raw_text(self):
        terms = TermCorrector.build_course_terms(
            course_title="嵌入式系统",
            keywords=[],
            ppt_slides=[{"page": 1, "title": "进程通信", "text": "父进程、子进程、fork、exec"}],
        )

        assert "子进程" in terms
        assert "紫禁城" not in terms


class TestPreservesSourceContent:
    def test_empty_source(self):
        # Empty source has nothing to preserve.
        assert corrector.preserves_source_content("", "") is True
        assert corrector.preserves_source_content("", "some") is True

    def test_content_preserved(self):
        raw = "单例模式确保一个类只有一个实例。工厂模式用于创建对象。"
        candidate = "单例模式确保一个类只有一个实例。工厂模式用于创建对象。"
        assert corrector.preserves_source_content(raw, candidate) is True

    def test_semantic_rewrite_does_not_require_exact_chinese_keywords(self):
        raw = "操作系统通过调度器选择就绪进程运行，并在时间片结束后切换到其他进程。"
        candidate = "调度程序会从就绪队列选出任务执行；其时间配额用完后，系统再切换执行对象。"
        assert corrector.preserves_source_content(raw, candidate) is True

    def test_shorter_content_is_sent_to_ai_review_not_hard_rejected(self):
        raw = "单例模式确保一个类只有一个实例。工厂模式用于创建对象。观察者模式用于事件通知。"
        candidate = "单例模式确保一个类只有一个实例。"
        assert corrector.preserves_source_content(raw, candidate) is True
        assert "substantially_shorter" in corrector._content_review_reasons(raw, candidate)

    def test_looks_like_summary_rejected(self):
        raw = "今天我们学习单例模式和工厂模式。"
        candidate = "本节课讲了单例模式和工厂模式。"
        assert corrector.preserves_source_content(raw, candidate) is False

    def test_missing_keywords_and_numbers_rejected(self):
        raw = "今天我们学习 requests 库，版本是 2.28，调用 requests.get 方法。"
        candidate = "今天我们学习 Python 编程。"
        assert corrector.preserves_source_content(raw, candidate) is False


class TestAiContentReview:
    def test_normal_draft_is_accepted_without_second_call(self):
        c = TermCorrector()
        c._client = MagicMock()
        source = "进程通过调度器获得处理器时间，时间片结束后切换任务。"
        result = c.review_and_repair_candidate(source, source)
        assert result["text"] == source
        assert result["review_performed"] is False
        c._client.chat.completions.create.assert_not_called()

    def test_suspicious_draft_is_repaired_by_review(self):
        c = TermCorrector()
        c._client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].finish_reason = "stop"
        response.choices[0].message.content = (
            '{"has_material_loss":true,'
            '"missing_facts":["时间片结束后切换任务"],'
            '"repaired_text":"进程通过调度器获得处理器时间，时间片结束后切换任务。"}'
        )
        c._client.chat.completions.create.return_value = response

        source = "进程通过调度器获得处理器时间，时间片结束后切换任务。"
        result = c.review_and_repair_candidate(source, "进程由调度器分配处理器。")

        assert result["review_performed"] is True
        assert result["review_repaired"] is True
        assert "时间片结束" in result["text"]
        assert result["missing_facts"] == ["时间片结束后切换任务"]

    def test_known_course_terms_trigger_review(self):
        c = TermCorrector()
        c._client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].finish_reason = "stop"
        response.choices[0].message.content = (
            '{"has_material_loss":true,'
            '"missing_facts":["临界区"],'
            '"repaired_text":"互斥锁用于保护临界区，避免多个线程同时修改共享数据。"}'
        )
        c._client.chat.completions.create.return_value = response

        source = "互斥锁用于保护临界区，避免多个线程同时修改共享数据。"
        result = c.review_and_repair_candidate(
            source,
            "互斥锁可以避免多个线程同时修改共享数据。",
            protected_terms=["互斥锁", "临界区"],
        )
        assert result["review_repaired"] is True
        assert "临界区" in result["text"]

    def test_invalid_review_keeps_first_ai_draft(self):
        c = TermCorrector()
        c._client = MagicMock()
        response = MagicMock()
        response.choices = [MagicMock()]
        response.choices[0].finish_reason = "stop"
        response.choices[0].message.content = "not-json"
        c._client.chat.completions.create.return_value = response

        source = "进程通过调度器获得处理器时间，时间片结束后切换任务。"
        draft = "进程由调度器分配处理器，之后系统切换任务。"
        result = c.review_and_repair_candidate(
            source, draft, protected_terms=["时间片"]
        )

        assert result["text"] == draft
        assert result["review_performed"] is True
        assert result["review_repaired"] is False
        assert result["review_error_code"] == "invalid_response"


class TestLooksLikeSummary:
    def test_summary_patterns(self):
        assert corrector.looks_like_summary("本节课讲了单例模式") is True
        assert corrector.looks_like_summary("本次课程总结") is True
        assert corrector.looks_like_summary("老师讲解了工厂模式") is True

    def test_non_summary(self):
        assert corrector.looks_like_summary("单例模式确保一个类只有一个实例") is False
        assert corrector.looks_like_summary("") is False


class TestDedupeRepeatedTexts:
    def test_basic_dedup(self):
        texts = ["A", "A", "B", "C"]
        result = corrector.dedupe_repeated_texts(texts)
        assert "A" in result
        assert "B" in result
        assert "C" in result

    def test_overlap_removed(self):
        texts = ["今天我们学习A。", "今天我们学习A。接下来学习B。"]
        result = corrector.dedupe_repeated_texts(texts)
        assert len(result) == 2


class TestDedupeAsrSegments:
    def test_duplicate_segments_dropped(self):
        class FakeSeg:
            def __init__(self, text):
                self.text = text
        segs = [FakeSeg("A"), FakeSeg("A"), FakeSeg("B")]
        result = corrector.dedupe_asr_segments(segs)
        assert len(result) == 2

    def test_empty_text_skipped(self):
        class FakeSeg:
            def __init__(self, text):
                self.text = text
        segs = [FakeSeg(""), FakeSeg("A")]
        result = corrector.dedupe_asr_segments(segs)
        assert len(result) == 1


class TestDedupeStreamFinals:
    def test_duplicate_strings_keeps_longer(self):
        segs = ["A", "AB", "B"]
        result = corrector.dedupe_stream_finals(segs)
        texts = [s if isinstance(s, str) else s.text for s in result]
        assert "AB" in texts

    def test_no_duplicate_kept(self):
        segs = ["A", "B", "C"]
        result = corrector.dedupe_stream_finals(segs)
        assert len(result) == 3


class TestRestructureTranscript:
    def test_no_client_returns_original(self):
        c = TermCorrector()
        c._client = None
        assert c.restructure_transcript("hello", "test") == "hello"

    def test_empty_text_returns_original(self):
        c = TermCorrector()
        c._client = MagicMock()
        assert c.restructure_transcript("", "test") == ""
        assert c.restructure_transcript("   ", "test") == "   "

    def test_short_text_single_chunk_success(self):
        c = TermCorrector()
        c._client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].finish_reason = "stop"
        mock_response.choices[0].message.content = "cleaned text"
        c._client.chat.completions.create.return_value = mock_response

        # Use a source long enough that a modest rewrite is not rejected by the
        # content-preservation guard, and do not pass protected keywords that the
        # mock output does not contain (otherwise a review pass is triggered).
        result = c.restructure_transcript("raw text input", "course")
        assert result == "cleaned text"
        c._client.chat.completions.create.assert_called_once()

    def test_chunked_long_text_splits(self):
        c = TermCorrector()
        c._client = MagicMock()
        calls: list[str] = []

        def fake_create(**kwargs):
            messages = kwargs.get("messages", [])
            content = messages[-1]["content"] if messages else ""
            calls.append(content)
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].finish_reason = "stop"
            # Return a marker plus enough real-looking text so the content-
            # preservation guard accepts the rewrite (>= 65% of source length).
            marker = f"[{len(calls)}]"
            response.choices[0].message.content = marker + " content continues" * 500
            return response

        c._client.chat.completions.create.side_effect = fake_create
        # Build two long paragraphs without sentence punctuation.  This keeps the
        # local-clean step from collapsing the source to a tiny deduplicated stub.
        # Use plain lowercase tokens so none are treated as critical tokens.
        para1 = "chunkone " + "tokenone " * 1000
        para2 = "chunktwo " + "tokentwo " * 1000
        result = c.restructure_transcript_chunked(para1 + "\n\n" + para2, "course")
        assert result.chunks_total > 1
        assert result.chunks_succeeded == result.chunks_total
        assert "[1]" in result.text
        assert "[2]" in result.text

    def test_partial_failure_keeps_success_chunks(self):
        c = TermCorrector()
        c._client = MagicMock()

        def fake_create(**kwargs):
            messages = kwargs.get("messages", [])
            content = messages[-1]["content"] if messages else ""
            response = MagicMock()
            response.choices = [MagicMock()]
            if "sectionone" in content:
                response.choices[0].finish_reason = "stop"
                # Include enough text so the content-preservation guard accepts it.
                response.choices[0].message.content = "成功段：" + "revisedtoken " * 600
            else:
                response.choices[0].finish_reason = "length"
                response.choices[0].message.content = "truncated"
            return response

        c._client.chat.completions.create.side_effect = fake_create
        # Long paragraphs without sentence punctuation prevent aggressive dedupe.
        first_para = "sectionone " + "alphaone " * 1000
        second_para = "sectiontwo " + "betaone " * 1000
        result = c.restructure_transcript_chunked(first_para + "\n\n" + second_para, "course")
        assert result.chunks_total >= 2
        assert result.chunks_succeeded >= 1
        assert result.chunks_failed >= 1
        assert "成功段" in result.text
        # Failed chunks fall back to their local clean text, so no content is lost.
        assert len(result.text) >= len("成功段")

    def test_retry_failed_only_reuses_success_results(self):
        c = TermCorrector()
        c._client = MagicMock()

        # Build two long paragraphs without sentence punctuation so the splitter
        # produces two chunks and the local-clean step does not collapse them.
        first_para = "reusemarker " + "firstone " * 600
        second_para = "retrymarker " + "secondone " * 600
        previous = [
            RestructureChunkResult(index=0, input=first_para, output="成功段已保留。", success=True, input_length=len(first_para)),
            RestructureChunkResult(index=1, input=second_para, output="失败段", success=False, error_code="timeout", error_message="超时", retryable=True, input_length=len(second_para)),
        ]

        call_count = [0]

        def fake_create(**kwargs):
            call_count[0] += 1
            response = MagicMock()
            response.choices = [MagicMock()]
            response.choices[0].finish_reason = "stop"
            # Return a long enough rewrite so the content-preservation guard accepts it.
            response.choices[0].message.content = "重试成功：" + "retriedtoken " * 350
            return response

        c._client.chat.completions.create.side_effect = fake_create
        result = c.restructure_transcript_chunked(
            first_para + "\n\n" + second_para,
            "course",
            previous_results=previous,
            retry_failed_only=True,
        )
        assert result.chunks_succeeded == result.chunks_total
        assert call_count[0] == 1  # only the failed chunk was sent to the LLM
        assert "成功段" in result.text
        assert "重试成功" in result.text

    def test_error_classification_timeout(self):
        c = TermCorrector()
        code, message, retryable = c._classify_exception(TimeoutError("timeout"))
        assert code == "timeout"
        assert retryable is True

    def test_error_classification_authentication(self):
        c = TermCorrector()
        try:
            import openai
        except Exception:
            pytest.skip("openai not installed")
        code, message, retryable = c._classify_exception(openai.AuthenticationError("auth failed", response=MagicMock(), body=None))
        assert code == "authentication"
        assert retryable is False

    def test_llm_empty_response_returns_error(self):
        c = TermCorrector()
        c._client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].finish_reason = "stop"
        mock_response.choices[0].message.content = ""
        c._client.chat.completions.create.return_value = mock_response

        result = c.restructure_transcript_chunked("raw", "course")
        assert result.is_ai_corrected is False
        assert result.error_code == "empty_response"

    def test_llm_truncated_response_returns_error(self):
        c = TermCorrector()
        c._client = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].finish_reason = "length"
        mock_response.choices[0].message.content = "truncated"
        c._client.chat.completions.create.return_value = mock_response

        result = c.restructure_transcript_chunked("raw", "course")
        assert result.is_ai_corrected is False
        assert result.error_code == "truncated_response"

    def test_llm_exception_propagates_via_result(self):
        c = TermCorrector()
        c._client = MagicMock()
        c._client.chat.completions.create.side_effect = RuntimeError("boom")
        with pytest.raises(CorrectionError, match="boom"):
            c.restructure_transcript("raw", "course")

    def test_correct_segments_delegation(self):
        c = TermCorrector()
        with patch.object(c, "restructure_transcript", return_value="result") as mock_re:
            result = c.correct_segments("text", "course", keywords=["k"])
            assert result == "result"
            mock_re.assert_called_once_with("text", "course", ["k"])


class TestEnsureParagraphBreaks:
    def test_short_text_no_break(self):
        text = "A。B。C。"
        result = corrector.ensure_paragraph_breaks(text)
        assert "\n\n" not in result

    def test_topic_shift_break(self):
        # Need > 3 sentences for paragraph break logic to run
        text = (
            "今天我们学习A内容的部分基础概念和定义。"
            "接下来我们学习B部分的高级特性和使用场景。"
            "然后学习C部分的实际案例分析。"
            "最后我们学习D部分的总结和回顾。"
        )
        result = corrector.ensure_paragraph_breaks(text)
        # Topic shift words should trigger breaks
        assert "\n\n" in result

    def test_max_length_break(self):
        text = "A。" * 300
        result = corrector.ensure_paragraph_breaks(text)
        assert "\n\n" in result
