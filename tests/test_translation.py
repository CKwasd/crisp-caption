from __future__ import annotations

from pathlib import Path

import pytest

from translation import (
    build_glossary_text,
    build_user_message,
    clean_translation_output,
    load_merged_glossary,
)


def test_clean_translation_output_strips_tags() -> None:
    text = "<source>こんにちは</source>\n<translation>你好</translation>"
    assert clean_translation_output(text) == "こんにちは\n你好"


def test_clean_translation_output_strips_leading_labels() -> None:
    assert clean_translation_output("譯文：こんにちは") == "こんにちは"
    assert clean_translation_output("译文：こんにちは") == "こんにちは"


def test_clean_translation_output_handles_blank() -> None:
    assert clean_translation_output("   \n ") == ""


def test_build_glossary_text_empty() -> None:
    assert build_glossary_text({}) == ""


def test_build_glossary_text_formats_lines() -> None:
    out = build_glossary_text({"配信": "直播", "VTuber": "VTuber"})
    assert "術語表（必須固定使用以下譯法）：" in out
    assert "- 配信 => 直播" in out
    assert "- VTuber => VTuber" in out


def test_build_user_message_no_context() -> None:
    msg = build_user_message("こんにちは", {})
    assert "こんにちは" in msg
    assert "繁體中文（台灣）" in msg


def test_build_user_message_with_glossary() -> None:
    msg = build_user_message("配信", {"配信": "直播"})
    assert "術語表" in msg
    assert "- 配信 => 直播" in msg


def test_build_user_message_with_history() -> None:
    history = [("こんにちは", "你好")]
    msg = build_user_message("今日は", {}, history=history)
    assert "こんにちは" in msg
    assert "你好" in msg


def test_load_merged_glossary_reads_file(tmp_path: Path) -> None:
    p = tmp_path / "glossary.json"
    p.write_text('{"配信": "直播"}', encoding="utf-8")
    assert load_merged_glossary(str(p)) == {"配信": "直播"}


def test_load_merged_glossary_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        load_merged_glossary(str(tmp_path / "nope.json"))
    assert excinfo.value.code == 2
