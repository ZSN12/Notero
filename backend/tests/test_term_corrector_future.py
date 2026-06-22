"""Tests for TermCorrector concurrent chunk resilience."""

from unittest.mock import patch

import pytest

from app.services.term_corrector import RestructureChunkResult, corrector


@pytest.fixture
def four_chunks():
    return [
        "今天我们学习 Python 的列表推导式，它是一种简洁的构建列表的方法。",
        "接下来介绍 NumPy 数组的广播机制，这会让矩阵运算非常高效。",
        "最后我们讨论 Pandas 的 DataFrame 索引与切片，注意 loc 和 iloc 的区别。",
        "课后请大家完成作业：读取 CSV 文件并统计每列的缺失值数量。",
    ]


def test_future_runtime_error_keeps_other_chunks(four_chunks):
    """When one chunk Future raises RuntimeError, the other 3 must still finish.

    The final result must be `partial` (succeeded > 0 and failed > 0) and must
    not collapse into a 0/0 unknown failure.
    """
    if not corrector.has_llm:
        pytest.skip("LLM client not configured")

    completed_calls = []

    def fake_process_chunk(index, text, prompt, system_msg, timeout_seconds=90.0, protected_terms=None):
        completed_calls.append(index)
        if index == 1:
            raise RuntimeError("simulated worker crash")
        return RestructureChunkResult(
            index=index,
            input=text,
            output=f"[ai]{text}",
            success=True,
            input_length=len(text),
        )

    progress_log = []

    def on_chunk_complete(completed_count, total):
        progress_log.append((completed_count, total))

    with patch.object(corrector, "_split_natural_chunks", return_value=four_chunks):
        with patch.object(corrector, "_process_chunk", side_effect=fake_process_chunk):
            result = corrector.restructure_transcript_chunked(
                "dummy",
                "测试课程",
                on_chunk_complete=on_chunk_complete,
            )

    assert result.chunks_total == 4
    assert result.chunks_succeeded == 3
    assert result.chunks_failed == 1
    # Partial success means the overall transcript was NOT fully AI-corrected.
    assert result.is_ai_corrected is False
    assert result.error_code == "unknown"
    assert len(completed_calls) == 4

    # Failed chunk should fall back to its local clean text.
    assert four_chunks[1] in result.text

    # Successful chunks must keep their AI output.
    assert f"[ai]{four_chunks[0]}" in result.text
    assert f"[ai]{four_chunks[2]}" in result.text
    assert f"[ai]{four_chunks[3]}" in result.text

    # Progress must be monotonic and reach 4/4.
    assert progress_log == [(1, 4), (2, 4), (3, 4), (4, 4)]
