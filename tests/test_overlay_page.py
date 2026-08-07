from __future__ import annotations

from overlay_page import obs_overlay_html, qt_overlay_html


def test_obs_defaults():
    html = obs_overlay_html("ws://127.0.0.1:8765/ws")
    assert "mode: 'both'" in html
    assert "holdMs: 2000" in html
    assert "fadeMs: 4000" in html
    assert "demo: false" in html
    assert "interjLen: 3" in html
    assert "interjRatio: 0.4" in html
    assert "interjGapMs: 2000" in html
    assert "-webkit-line-clamp: 3" in html
    assert "align-items: end" in html
    assert "clamp(28px, 4.20vw, 58px)" in html
    assert html.index('id="trans"') < html.index('id="main"') < html.index('id="partial"')
    assert "min-height: 1.28em" in html
    assert "transform: translateY(6px)" not in html


def test_obs_options():
    html = obs_overlay_html(
        "ws://x/ws",
        mode="both",
        hold_sec=1,
        fade_sec=0,
        font=2,
        pos="top",
        demo=True,
        interj_len=5,
        interj_ratio=0.3,
        interj_gap_sec=1.5,
    )
    assert "mode: 'both'" in html
    assert "holdMs: 1000" in html
    assert "fadeMs: 0" in html
    assert "demo: true" in html
    assert "interjLen: 5" in html
    assert "interjRatio: 0.3" in html
    assert "interjGapMs: 1500" in html
    assert "align-items: start" in html
    assert "clamp(56px, 8.40vw, 116px)" in html


def test_qt_html():
    html = qt_overlay_html("ws://x/ws", 34, mode="source", hold_sec=0.5, fade_sec=2)
    assert "font-size: 34px" in html
    assert "font-size: 24px" in html
    assert "mode: 'source'" in html
    assert "holdMs: 500" in html
    assert "fadeMs: 2000" in html
    assert "mode: 'both'" in qt_overlay_html("ws://x/ws", 34)
