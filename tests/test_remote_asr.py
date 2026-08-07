from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

aiohttp_stub = types.ModuleType("aiohttp")
aiohttp_stub.web = types.SimpleNamespace(WebSocketResponse=object)
sys.modules.setdefault("aiohttp", aiohttp_stub)

from bridge_config import parse_args, run_config_from_ns
from bridge_state import BridgeRealtimeState
from crisp_process import MAX_TRANSLATE_QUEUE, CrispEventRelay, enqueue_translation


class RemoteAsrConfigTests(unittest.TestCase):
    def test_remote_profile_keeps_crisp_paths_for_colab(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "asr_mode": "remote",
                        "remote_asr_url": "wss://example.test/asr/stream",
                        "crisp_args": ["-m", "models/asr/model.gguf", "-vm", "models/vad/vad.gguf"],
                    }
                ),
                encoding="utf-8",
            )
            ns, crisp_args = parse_args(["bridge_server.py", "--config", str(profile)])
        self.assertEqual(ns.asr_mode, "remote")
        self.assertEqual(crisp_args, ["-m", "models/asr/model.gguf", "-vm", "models/vad/vad.gguf"])

    def test_local_profile_resolves_crisp_paths_relative_to_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile.json"
            profile.write_text(
                json.dumps({"crisp_args": ["-m", "../models/asr/model.gguf"]}),
                encoding="utf-8",
            )
            _, crisp_args = parse_args(["bridge_server.py", "--config", str(profile)])
            expected = str((profile.parent / "../models/asr/model.gguf").resolve())
        self.assertEqual(crisp_args, ["-m", expected])

    def test_overlay_interj_defaults_from_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "crisp_args": [],
                        "overlay_interj_len": 5,
                        "overlay_interj_ratio": 0.3,
                        "overlay_interj_gap_sec": 1.5,
                    }
                ),
                encoding="utf-8",
            )
            ns, crisp_args = parse_args(["bridge_server.py", "--config", str(profile)])
            cfg = run_config_from_ns(ns, crisp_args)
        self.assertEqual(cfg.overlay_interj_len, 5)
        self.assertEqual(cfg.overlay_interj_ratio, 0.3)
        self.assertEqual(cfg.overlay_interj_gap_sec, 1.5)

    def test_overlay_interj_cli_overrides_default(self) -> None:
        ns, crisp_args = parse_args(
            ["bridge_server.py", "--overlay-interj-len", "6", "--overlay-interj-ratio", "0.5"]
        )
        cfg = run_config_from_ns(ns, crisp_args)
        self.assertEqual(cfg.overlay_interj_len, 6)
        self.assertEqual(cfg.overlay_interj_ratio, 0.5)
        self.assertEqual(cfg.overlay_interj_gap_sec, 2.0)

    def test_overlay_mode_from_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile.json"
            profile.write_text(
                json.dumps({"crisp_args": [], "overlay_mode": "source"}),
                encoding="utf-8",
            )
            ns, crisp_args = parse_args(["bridge_server.py", "--config", str(profile)])
            cfg = run_config_from_ns(ns, crisp_args)
        self.assertEqual(cfg.overlay_mode, "source")

    def test_overlay_mode_cli_overrides_default(self) -> None:
        ns, crisp_args = parse_args(["bridge_server.py", "--overlay-mode", "source"])
        cfg = run_config_from_ns(ns, crisp_args)
        self.assertEqual(cfg.overlay_mode, "source")


class CrispEventRelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_final_event_enqueues_translation(self) -> None:
        state = BridgeRealtimeState(transcript_queue=asyncio.Queue())
        relay = CrispEventRelay(
            state,
            enqueue_for_translate=True,
            print_raw_crisp_events=False,
            debug_timestamps=False,
        )
        await relay.handle_line('{"type":"final","text":"hello","utterance_id":7,"t0":0.1,"t1":1.2}')
        self.assertEqual(state.transcript_seq, 1)
        self.assertEqual(await state.transcript_queue.get(), (1, "hello"))

    async def test_malformed_json_becomes_plain_transcript(self) -> None:
        state = BridgeRealtimeState(transcript_queue=asyncio.Queue())
        relay = CrispEventRelay(
            state,
            enqueue_for_translate=True,
            print_raw_crisp_events=False,
            debug_timestamps=False,
        )
        await relay.handle_line("plain text")
        self.assertEqual(state.transcript_seq, 1)
        self.assertEqual(await state.transcript_queue.get(), (1, "plain text"))

    async def test_silence_does_not_enqueue_translation(self) -> None:
        state = BridgeRealtimeState(transcript_queue=asyncio.Queue())
        relay = CrispEventRelay(
            state,
            enqueue_for_translate=True,
            print_raw_crisp_events=False,
            debug_timestamps=False,
        )
        await relay.handle_line('{"type":"silence","t":2.0}')
        self.assertEqual(state.transcript_queue.qsize(), 0)

    async def test_translate_queue_drops_oldest(self) -> None:
        state = BridgeRealtimeState(transcript_queue=asyncio.Queue())
        for i in range(MAX_TRANSLATE_QUEUE + 5):
            await enqueue_translation(state, i, f"t{i}")
        self.assertEqual(state.transcript_queue.qsize(), MAX_TRANSLATE_QUEUE)
        first = await state.transcript_queue.get()
        self.assertEqual(first, (5, "t5"))


if __name__ == "__main__":
    unittest.main()
