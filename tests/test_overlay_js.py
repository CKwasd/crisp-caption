from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from overlay_page import obs_overlay_html

HERE = Path(__file__).parent
HARNESS = HERE / "overlay_harness.js"


def _extract_js() -> str:
    html = obs_overlay_html("ws://127.0.0.1:8765/ws")
    match = re.search(r"<script>(.*?)</script>", html, re.S)
    assert match is not None
    return match.group(1)


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_overlay_js_timing(tmp_path: Path) -> None:
    check_js = tmp_path / "overlay_check.js"
    check_js.write_text(_extract_js(), encoding="utf-8")
    result = subprocess.run(
        ["node", str(HARNESS), str(check_js)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"overlay JS check failed:\n{result.stdout}\n{result.stderr}"
