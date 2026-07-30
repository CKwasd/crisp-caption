from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
import re
import time

from bridge_state import BridgeRealtimeState, broadcast_health, broadcast_json

logger = logging.getLogger(__name__)

# ponytail: drop oldest when translator lags; raise if OOM under burst load
MAX_TRANSLATE_QUEUE = 32


async def enqueue_translation(state: BridgeRealtimeState, seq: int, text: str) -> None:
    q = state.transcript_queue
    while q.qsize() >= MAX_TRANSLATE_QUEUE:
        try:
            q.get_nowait()
            q.task_done()
        except asyncio.QueueEmpty:
            break
    await q.put((seq, text))


class CrispEventRelay:
    def __init__(
        self,
        state: BridgeRealtimeState,
        *,
        enqueue_for_translate: bool,
        print_raw_crisp_events: bool,
        debug_timestamps: bool,
    ) -> None:
        self.state = state
        self.enqueue_for_translate = enqueue_for_translate
        self.print_raw_crisp_events = print_raw_crisp_events
        self.debug_timestamps = debug_timestamps
        self.first_event_mono: float | None = None
        self.first_event_audio_t: float | None = None
        self.last_event_mono: float | None = None
        self.last_event_audio_t: float | None = None

    def add_debug_timestamps(self, obj: dict[str, object], audio_t: float | None) -> dict[str, object]:
        if not self.debug_timestamps:
            return obj

        now_mono = time.monotonic()
        if self.first_event_mono is None:
            self.first_event_mono = now_mono
            self.first_event_audio_t = audio_t

        out = dict(obj)
        elapsed = now_mono - self.first_event_mono
        out["dbg_wall"] = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        out["dbg_elapsed_sec"] = round(elapsed, 3)

        if self.last_event_mono is not None:
            out["dbg_gap_sec"] = round(now_mono - self.last_event_mono, 3)
        if audio_t is not None:
            out["dbg_audio_t"] = round(audio_t, 3)
            if self.first_event_audio_t is not None:
                audio_elapsed = audio_t - self.first_event_audio_t
                out["dbg_audio_elapsed_sec"] = round(audio_elapsed, 3)
                out["dbg_lag_sec"] = round(elapsed - audio_elapsed, 3)
            if self.state.first_pcm_mono is not None:
                live_audio_elapsed = audio_t - self.state.stream_preload_sec
                live_elapsed = now_mono - self.state.first_pcm_mono
                out["dbg_live_elapsed_sec"] = round(live_elapsed, 3)
                out["dbg_live_audio_elapsed_sec"] = round(live_audio_elapsed, 3)
                out["dbg_live_lag_sec"] = round(live_elapsed - live_audio_elapsed, 3)
            if self.last_event_audio_t is not None:
                out["dbg_audio_gap_sec"] = round(audio_t - self.last_event_audio_t, 3)

        self.last_event_mono = now_mono
        if audio_t is not None:
            self.last_event_audio_t = audio_t
        return out

    async def handle_line(self, text: str) -> None:
        text = text.strip()
        if not text:
            return

        state = self.state
        try:
            event = json.loads(text)
        except json.JSONDecodeError:
            event = None

        if isinstance(event, dict) and isinstance(event.get("type"), str):
            kind = str(event["type"])
            if kind in {"partial", "final"}:
                if state.suppress_transcripts:
                    return
                state.transcript_seq += 1
                seq = state.transcript_seq
                utterance_id = event.get("utterance_id")
                transcript_text = str(event.get("text") or "")
                payload: dict[str, object] = {
                    "type": "transcript",
                    "seq": seq,
                    "kind": kind,
                    "final": kind == "final",
                    "text": transcript_text,
                }
                if isinstance(utterance_id, int):
                    payload["utterance_id"] = utterance_id
                t1: float | None = None
                for key in ("t0", "t1"):
                    val = event.get(key)
                    if isinstance(val, (int, float)):
                        payload[key] = val
                        if key == "t1":
                            t1 = float(val)
                if t1 is not None:
                    state.last_audio_t = t1
                terminal_payload = event if self.print_raw_crisp_events else payload
                print(json.dumps(self.add_debug_timestamps(terminal_payload, t1), ensure_ascii=False), flush=True)
                if kind != "final" or transcript_text.strip():
                    await broadcast_json(state.ws_clients, payload)
                if t1 is not None:
                    await broadcast_health(state)
                if self.enqueue_for_translate and kind == "final" and transcript_text.strip():
                    await enqueue_translation(state, seq, transcript_text)
                return

            if kind == "silence":
                if state.suppress_transcripts:
                    return
                payload = {"type": "silence"}
                audio_t: float | None = None
                val = event.get("t")
                if isinstance(val, (int, float)):
                    payload["t"] = val
                    audio_t = float(val)
                if audio_t is not None:
                    state.last_audio_t = audio_t
                    await broadcast_health(state)
                terminal_payload = event if self.print_raw_crisp_events else payload
                print(json.dumps(self.add_debug_timestamps(terminal_payload, audio_t), ensure_ascii=False), flush=True)
                await broadcast_json(state.ws_clients, payload)
                return

        state.transcript_seq += 1
        seq = state.transcript_seq
        payload = {"type": "transcript", "seq": seq, "kind": "plain", "final": True, "text": text}
        print(json.dumps(self.add_debug_timestamps(payload, None), ensure_ascii=False), flush=True)
        await broadcast_json(state.ws_clients, payload)
        if self.enqueue_for_translate:
            await enqueue_translation(state, seq, text)
            await broadcast_health(state)


async def relay_stdout(
    proc: asyncio.subprocess.Process,
    state: BridgeRealtimeState,
    *,
    enqueue_for_translate: bool,
    print_raw_crisp_events: bool,
    debug_timestamps: bool,
) -> None:
    assert proc.stdout
    relay = CrispEventRelay(
        state,
        enqueue_for_translate=enqueue_for_translate,
        print_raw_crisp_events=print_raw_crisp_events,
        debug_timestamps=debug_timestamps,
    )
    while True:
        raw = await proc.stdout.readline()
        if not raw:
            break
        await relay.handle_line(raw.decode("utf-8", errors="replace"))


SAMPLE_RATE = 16000

# PowerShell quoting mistakes occasionally produce ONE argv whose value looks like "--flag value".
_MERGED_LONG_FLAG_NUM = re.compile(
    r"^--(?P<flag>stream-length|stream-step|stream-keep|stream-final-on-silence-ms|stream-utterance-max-sec|"
    r"stream-final-mode|flush-after|max-new-tokens|chunk-seconds|"
    r"tts-steps|tts-max-input-chars|vad-min-speech-duration-ms|vad-min-silence-duration-ms|vad-speech-pad-ms|"
    r"vad-max-speech-duration-s|vad-samples-overlap|vad-threshold)\s+(?P<val>\S.+)$",
    re.IGNORECASE,
)
_MERGED_SHORT_NUM = re.compile(
    r"^-(?P<f>vt|vspd|vsd|vp|vmsd|vo)\s+(?P<val>\S.+)$",
    re.IGNORECASE,
)


def normalize_crisp_argv(tokens: list[str]) -> list[str]:
    """Fix argv where flag and value were stuck in one string (seen with PowerShell)."""

    expanded: list[str] = []

    def push_pair(flag: str, val: str) -> None:
        expanded.append(flag)
        expanded.append(val.strip())

    for raw in tokens:
        m = _MERGED_LONG_FLAG_NUM.match(raw.strip())
        if m:
            fl = "--" + m.group("flag").lower()
            vl = m.group("val").strip()
            logger.info("Normalizing merged CrispASR flag %r -> %s + %s", raw, fl, repr(vl)[:120])
            push_pair(fl, vl)
            continue
        ms = _MERGED_SHORT_NUM.match(raw.strip())
        if ms and ms.group("f"):
            fl = "-" + ms.group("f").lower()
            vl = ms.group("val").strip()
            logger.info("Normalizing merged CrispASR flag %r -> %s + %s", raw, fl, repr(vl)[:120])
            push_pair(fl, vl)
            continue
        expanded.append(raw)

    return expanded


def build_crispasr_cmd(crisp_exe: str, extra: list[str]) -> list[str]:
    base = ["--stream", "--monitor", "--no-prints"]
    return [crisp_exe, *base, *extra]


def stream_step_bytes_from_extra(extra: list[str], sample_rate: int = SAMPLE_RATE) -> int:
    """Bytes per stream step (s16le mono), for one crispasr fread chunk."""
    step_ms = 3000
    for i, token in enumerate(extra):
        if token == "--stream-step" and i + 1 < len(extra):
            try:
                step_ms = max(1, int(extra[i + 1]))
            except ValueError:
                pass
            break
    n_samples = step_ms * sample_rate // 1000
    return n_samples * 2


async def relay_stderr(proc: asyncio.subprocess.Process, *, crisp_verbose: bool) -> None:
    """Forward CrispASR diagnostics (Vulkan, missing model paths, backend init failures).

    With ``crisp_verbose`` (``-v``): log at INFO. Otherwise DEBUG so the terminal is not flooded
    (firered_vad, etc.) while transcript JSON on stdout stays the visible result.
    """

    assert proc.stderr
    enc = "utf-8"
    logfn = logger.info if crisp_verbose else logger.debug

    while True:
        raw = await proc.stderr.readline()
        if not raw:
            break
        line = raw.decode(enc, errors="replace").rstrip()
        if line:
            logfn("%s", line)


async def pcm_writer(proc: asyncio.subprocess.Process, q: asyncio.Queue[bytes]) -> None:
    assert proc.stdin
    stdin = proc.stdin

    while True:
        chunk = await q.get()
        stdin.write(chunk)
        await stdin.drain()
