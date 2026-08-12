from __future__ import annotations

import os
import sys
import types
import unittest

# Stub heavy third-party deps so bridge_runtime can import without av/aiortc/avx.
sys.modules.setdefault(
    "aiohttp",
    types.ModuleType(
        "__aiohttp__",
    ),
)
_aiohttp = sys.modules["aiohttp"]
_aiohttp.web = types.SimpleNamespace(WebSocketResponse=object)
_aiohttp.WSMsgType = types.SimpleNamespace(TEXT=1, ERROR=2)

sys.modules.setdefault("av", types.ModuleType("__av__"))
_aiortc = types.ModuleType("__aiortc__")
_aiortc.MediaStreamTrack = type("MediaStreamTrack", (), {})
_aiortc.RTCPeerConnection = type("RTCPeerConnection", (), {})
_aiortc.RTCSessionDescription = type("RTCSessionDescription", (), {})
sys.modules["aiortc"] = _aiortc
# av.audio.AudioResampler is only referenced at runtime (inside function), not import time.
sys.modules.setdefault("PySide6", types.ModuleType("__pyside6__"))

from bridge_config import BridgeRunConfig  # noqa: E402
from bridge_runtime import apply_source_overrides  # noqa: E402


def _make_cfg() -> BridgeRunConfig:
    # Minimal config with a translate_url default so overrides have a base.
    return BridgeRunConfig(
        crisp_exe="crispasr",
        crisp_args=[],
        asr_mode="local",
        translate_url="http://127.0.0.1:8080/v1/chat/completions",
        translate_enabled=False,
    )


class ApplySourceOverridesTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("CRISPASR_REMOTE_KEY", None)
        os.environ.pop("OPENAI_API_KEY", None)

    def test_asr_remote_sets_url_key_and_env(self) -> None:
        cfg = _make_cfg()
        cfg.asr_mode = "local"
        apply_source_overrides(
            cfg,
            {"mode": "remote", "url": "wss://x/asr/stream", "key": "asrkey123"},
            None,
        )
        self.assertEqual(cfg.asr_mode, "remote")
        self.assertEqual(cfg.remote_asr_url, "wss://x/asr/stream")
        self.assertEqual(cfg.remote_asr_bearer, "asrkey123")
        self.assertEqual(os.environ.get("CRISPASR_REMOTE_KEY"), "asrkey123")

    def test_asr_local_resets_mode(self) -> None:
        cfg = _make_cfg()
        cfg.asr_mode = "remote"
        apply_source_overrides(cfg, {"mode": "local"}, None)
        self.assertEqual(cfg.asr_mode, "local")

    def test_translate_remote_sets_url_key_env(self) -> None:
        cfg = _make_cfg()
        apply_source_overrides(
            cfg,
            None,
            {"mode": "remote", "url": "https://x/v1/chat/completions", "key": "transkey456"},
        )
        self.assertEqual(cfg.translate_url, "https://x/v1/chat/completions")
        self.assertTrue(cfg.translate_enabled)
        self.assertEqual(cfg.translate_bearer, "transkey456")
        self.assertEqual(os.environ.get("OPENAI_API_KEY"), "transkey456")

    def test_translate_remote_without_key_keeps_env(self) -> None:
        os.environ["OPENAI_API_KEY"] = "existing"
        cfg = _make_cfg()
        apply_source_overrides(
            cfg, None, {"mode": "remote", "url": "https://x/v1/chat/completions"}
        )
        self.assertEqual(cfg.translate_url, "https://x/v1/chat/completions")
        # no key provided: env untouched
        self.assertEqual(os.environ.get("OPENAI_API_KEY"), "existing")


if __name__ == "__main__":
    unittest.main()
