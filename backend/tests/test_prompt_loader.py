import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.services import prompt_loader
from app.services.prompt_loader import PromptTemplateError, load_prompt


def test_load_prompt_parses_system_and_user_template():
    load_prompt.cache_clear()
    prompt = load_prompt("asr_correction")

    assert "课堂语音转写" in prompt.system
    rendered = prompt.render(
        course_title="操作系统",
        keywords="进程、管道",
        text="我们讲 fork 和 pipe。",
        timestamped_text="00:00 我们讲 fork 和 pipe。",
    )
    assert "课程名称：操作系统" in rendered
    assert "课程关键词：进程、管道" in rendered
    assert "我们讲 fork 和 pipe。" in rendered


def test_load_prompt_rejects_missing_template_variable():
    load_prompt.cache_clear()
    prompt = load_prompt("asr_correction")

    with pytest.raises(PromptTemplateError, match="missing template variable"):
        prompt.render()


def test_load_prompt_reports_missing_file():
    load_prompt.cache_clear()

    with pytest.raises(PromptTemplateError, match="Prompt file not found"):
        load_prompt("does_not_exist")


def test_load_prompt_reports_missing_sections(tmp_path, monkeypatch):
    (tmp_path / "broken.md").write_text("## System\nOnly system", encoding="utf-8")
    monkeypatch.setattr(prompt_loader, "PROMPT_DIR", tmp_path)
    load_prompt.cache_clear()

    with pytest.raises(PromptTemplateError, match="User Template"):
        load_prompt("broken")


def test_asr_prompt_does_not_use_summary_role_language():
    load_prompt.cache_clear()
    prompt = load_prompt("asr_correction")
    combined = f"{prompt.system}\n{prompt.user_template}"

    assert "课程内容总结助手" not in combined
    assert "课堂总结" not in combined
    assert "本节课讲了" not in combined
    assert "老师讲了" not in combined
    assert "不要总结" in combined



