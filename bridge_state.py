from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field

from aiohttp import web


@dataclass
class BridgeRealtimeState:
    transcript_queue: asyncio.Queue[tuple[int, str]]
    ws_clients: set[web.WebSocketResponse] = field(default_factory=set)
    transcript_seq: int = 0
    translator_status: str = "disabled"
    translation_queue_size: int = 0
    last_error: str = ""
    first_pcm_mono: float | None = None
    stream_preload_sec: float = 0.0
    suppress_transcripts: bool = False
    active_profile: str = ""
    crisp_status: str = "stopped"
    crisp_epoch: int = 0
    last_audio_t: float | None = None
    overlay_interj_len: int = 3
    overlay_interj_ratio: float = 0.4
    overlay_interj_gap_sec: float = 2.0
    overlay_mode: str = "both"


def _calc_lag_sec(state: BridgeRealtimeState) -> float:
    if state.first_pcm_mono is None or state.last_audio_t is None:
        return 0.0
    wall = time.monotonic() - state.first_pcm_mono
    aud = state.last_audio_t - state.stream_preload_sec
    return round(wall - aud, 1)


async def broadcast_health(state: BridgeRealtimeState) -> None:
    state.translation_queue_size = state.transcript_queue.qsize()
    await broadcast_json(
        state.ws_clients,
        {
            "type": "health",
            "translator_status": state.translator_status,
            "translation_queue_size": state.translation_queue_size,
            "last_error": state.last_error,
            "active_profile": state.active_profile,
            "crisp_status": state.crisp_status,
            "crisp_epoch": state.crisp_epoch,
            "latency_sec": _calc_lag_sec(state),
        },
    )



async def broadcast_json(ws_clients: set[web.WebSocketResponse], obj: dict[str, object]) -> None:
    if not ws_clients:
        return
    line = json.dumps(obj, ensure_ascii=False)
    dead: list[web.WebSocketResponse] = []
    for ws in list(ws_clients):
        try:
            await ws.send_str(line)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)
