from __future__ import annotations

from datetime import datetime
from io import BytesIO
import re
from textwrap import wrap


def _safe_title(value: str | None) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", (value or "课堂转写").strip())
    return cleaned[:80] or "课堂转写"


def _wrap_cjk_text(text: str, chars_per_line: int) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            lines.append("")
            continue
        lines.extend(wrap(line, width=chars_per_line, break_long_words=True, replace_whitespace=False))
    return lines


def build_transcript_pdf(
    *,
    title: str,
    notebook_title: str,
    duration: str | None,
    transcript_text: str,
) -> tuple[bytes, str]:
    """Build a Chinese-friendly transcript PDF and return (bytes, filename)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen import canvas

    if not transcript_text.strip():
        raise ValueError("没有可导出的转写内容")

    font_name = "STSong-Light"
    pdfmetrics.registerFont(UnicodeCIDFont(font_name))

    buffer = BytesIO()
    page_width, page_height = A4
    margin_x = 17 * mm
    margin_top = 18 * mm
    margin_bottom = 16 * mm
    content_width = page_width - margin_x * 2
    y = page_height - margin_top

    c = canvas.Canvas(buffer, pagesize=A4)
    c.setTitle(title)

    def new_page() -> None:
        nonlocal y
        c.showPage()
        y = page_height - margin_top

    def ensure_space(height: float) -> None:
        if y - height < margin_bottom:
            new_page()

    def draw_line(text: str, *, font_size: int = 11, color=colors.HexColor("#1e293b"), leading: float = 6 * mm) -> None:
        nonlocal y
        ensure_space(leading)
        c.setFillColor(color)
        c.setFont(font_name, font_size)
        c.drawString(margin_x, y, text)
        y -= leading

    draw_line(title, font_size=18, color=colors.HexColor("#0f172a"), leading=8 * mm)
    meta = f"{notebook_title or '未知科目'}  |  时长 {duration or '-'}  |  {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    draw_line(meta, font_size=9, color=colors.HexColor("#64748b"), leading=7 * mm)

    ensure_space(8 * mm)
    c.setStrokeColor(colors.HexColor("#e2e8f0"))
    c.setLineWidth(1)
    c.line(margin_x, y, margin_x + content_width, y)
    y -= 8 * mm

    draw_line("转写内容", font_size=13, color=colors.HexColor("#0f172a"), leading=7 * mm)

    chars_per_line = max(24, int(content_width / (5.2 * mm)))
    for paragraph in re.split(r"\n{2,}", transcript_text.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for line in _wrap_cjk_text(paragraph, chars_per_line):
            if line:
                draw_line(line, font_size=10, leading=5.8 * mm)
            else:
                y -= 3 * mm
        y -= 2.5 * mm

    c.save()
    return buffer.getvalue(), f"{_safe_title(title)}.pdf"
