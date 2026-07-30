from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import wave
from collections.abc import Mapping
from pathlib import Path

import aiohttp

from bridge_state import BridgeRealtimeState, broadcast_health
from crisp_process import (
    SAMPLE_RATE,
    CrispEventRelay,
    build_crispasr_cmd,
    pcm_writer,
    relay_stderr,
    relay_stdout,
    stream_step_bytes_from_extra,
)

logger = logging.getLogger(__name__)


def load_warmup_pcm(path: str, max_sec: float, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Load up to max_sec of 16-bit mono PCM from WAV or raw s16le. Empty path → silence."""
    n = max(0, int(max_sec * sample_rate * 2))
    if n <= 0:
        return b""
    if not path:
        return b"\x00" * n
    p = Path(path)
    if not p.is_file():
        logger.warning("warmup_audio not found: %s (using silence)", path)
        return b"\x00" * n
    suffix = p.suffix.lower()
    if suffix in {".pcm", ".s16le", ".raw"}:
        data = p.read_bytes()
        return data[:n] if len(data) >= n else data + b"\x00" * (n - len(data))
    if suffix == ".wav":
        with wave.open(str(p), "rb") as w:
            if w.getnchannels() != 1 or w.getsampwidth() != 2:
                logger.warning("warmup WAV must be mono 16-bit; using silence (%s)", path)
                return b"\x00" * n
            if w.getframerate() != sample_rate:
                logger.warning(
                    "warmup WAV rate %d != %d; using as-is (best-effort)",
                    w.getframerate(),
                    sample_rate,
                )
            data = w.readframes(int(max_sec * w.getframerate()) + 1)
        return data[:n] if len(data) >= n else data + b"\x00" * (n - len(data))
    logger.warning("warmup_audio unsupported type %s (use .wav/.s16le); silence", suffix)
    return b"\x00" * n


async def feed_warmup_pcm(
    pcm_queue: asyncio.Queue[bytes],
    pcm: bytes,
    *,
    chunk_ms: int = 100,
    sample_rate: int = SAMPLE_RATE,
) -> None:
    if not pcm:
        return
    chunk = max(2, int(sample_rate * 2 * chunk_ms / 1000))
    if chunk % 2:
        chunk += 1
    for i in range(0, len(pcm), chunk):
        await pcm_queue.put(pcm[i : i + chunk])


class LocalCrispAsrBackend:
    def __init__(
        self,
        *,
        state: BridgeRealtimeState,
        pcm_queue: asyncio.Queue[bytes],
        crisp_exe: str,
        crisp_args: list[str],
        profile_name: str,
        crisp_hide_stderr: bool,
        verbose: bool,
        enqueue_for_translate: bool,
        print_raw_crisp_events: bool,
        debug_timestamps: bool,
        warmup_sec: float = 0.0,
        warmup_audio: str = "",
    ) -> None:
        self.state = state
        self.pcm_queue = pcm_queue
        self.crisp_exe = crisp_exe
        self.crisp_args = crisp_args
        self.profile_name = profile_name
        self.crisp_hide_stderr = crisp_hide_stderr
        self.verbose = verbose
        self.enqueue_for_translate = enqueue_for_translate
        self.print_raw_crisp_events = print_raw_crisp_events
        self.debug_timestamps = debug_timestamps
        self.warmup_sec = max(0.0, float(warmup_sec or 0.0))
        self.warmup_audio = (warmup_audio or "").strip()
        self.proc: asyncio.subprocess.Process | None = None
        self.tasks: list[asyncio.Task[object]] = []

    async def start(self) -> None:
        exe = self._resolve_executable(self.crisp_exe)
        if not exe:
            self.state.crisp_status = "error"
            self.state.active_profile = self.profile_name
            self.state.last_error = f"Cannot find crispasr executable: {self.crisp_exe!r}"
            await broadcast_health(self.state)
            raise FileNotFoundError(self.state.last_error)
        if not self.crisp_args:
            self.state.crisp_status = "error"
            self.state.active_profile = self.profile_name
            self.state.last_error = "No CrispASR arguments in selected profile."
            await broadcast_health(self.state)
            raise ValueError(self.state.last_error)

        cmd = build_crispasr_cmd(exe, self.crisp_args)
        logger.info("Spawning profile=%s: %s", self.profile_name, " ".join(cmd))

        cwd_path = os.path.dirname(os.path.abspath(exe))
        cwd = cwd_path if cwd_path and os.path.isdir(cwd_path) else None
        stderr_arg = asyncio.subprocess.DEVNULL if self.crisp_hide_stderr else asyncio.subprocess.PIPE
        self.state.active_profile = self.profile_name
        self.state.crisp_status = "starting"
        self.state.last_error = ""
        await broadcast_health(self.state)

        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=stderr_arg,
            cwd=cwd,
            limit=1024 * 1024,
        )

        self.tasks = [
            asyncio.create_task(pcm_writer(self.proc, self.pcm_queue)),
            asyncio.create_task(
                relay_stdout(
                    self.proc,
                    self.state,
                    enqueue_for_translate=self.enqueue_for_translate,
                    print_raw_crisp_events=self.print_raw_crisp_events,
                    debug_timestamps=self.debug_timestamps,
                )
            ),
            asyncio.create_task(self._watch_child(self.proc)),
        ]
        if self.proc.stderr:
            self.tasks.append(asyncio.create_task(relay_stderr(self.proc, crisp_verbose=self.verbose)))

        preload = stream_step_bytes_from_extra(self.crisp_args)
        self.state.stream_preload_sec = preload / (2 * SAMPLE_RATE)
        logger.info("Queueing initial %d-byte silence (one Crisp stream step) onto stdin.", preload)
        await self.pcm_queue.put(b"\x00" * preload)

        if self.warmup_sec > 0:
            await self._run_warmup()
        else:
            self.state.suppress_transcripts = False
            self.state.crisp_status = "running"
            await broadcast_health(self.state)

    async def _run_warmup(self) -> None:
        self.state.suppress_transcripts = True
        self.state.crisp_status = "warming"
        await broadcast_health(self.state)
        pcm = load_warmup_pcm(self.warmup_audio, self.warmup_sec)
        src = self.warmup_audio or "silence"
        logger.info("Warmup %.1fs via %s (%d bytes)", self.warmup_sec, src, len(pcm))
        await feed_warmup_pcm(self.pcm_queue, pcm)
        # let crispasr drain + finish first graphs; silence settles faster than speech
        settle = min(8.0, max(1.5, self.warmup_sec * 0.35))
        await asyncio.sleep(settle)
        self.state.suppress_transcripts = False
        self.state.first_pcm_mono = None
        self.state.crisp_status = "running"
        await broadcast_health(self.state)
        logger.info("Warmup done (settled %.1fs); live transcripts enabled", settle)

    async def stop(self) -> None:
        self.state.suppress_transcripts = False
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []

        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        self.proc = None

    async def _watch_child(self, proc: asyncio.subprocess.Process) -> None:
        rc = await proc.wait()
        if proc is not self.proc:
            return
        if rc != 0:
            msg = f"CrispASR profile {self.profile_name!r} exited with code {rc}"
            logger.warning("%s", msg)
            self.state.last_error = msg
            self.state.crisp_status = "error"
        else:
            logger.warning("CrispASR profile %r exited cleanly.", self.profile_name)
            self.state.crisp_status = "stopped"
        await broadcast_health(self.state)

    @staticmethod
    def _resolve_executable(crisp_exe: str) -> str | None:
        if os.path.isfile(crisp_exe):
            return crisp_exe
        resolved = shutil.which(crisp_exe)
        if resolved and os.path.isfile(resolved):
            return resolved
        return None


class RemoteCrispAsrBackend:
    def __init__(
        self,
        *,
        state: BridgeRealtimeState,
        pcm_queue: asyncio.Queue[bytes],
        remote_asr_url: str,
        bearer: str | None,
        crisp_args: list[str],
        profile_name: str,
        enqueue_for_translate: bool,
        print_raw_crisp_events: bool,
        debug_timestamps: bool,
        bearer_env: str = "CRISPASR_REMOTE_TOKEN",
    ) -> None:
        self.state = state
        self.pcm_queue = pcm_queue
        self.remote_asr_url = remote_asr_url
        self.bearer = bearer
        self.bearer_env = bearer_env or "CRISPASR_REMOTE_TOKEN"
        self.crisp_args = crisp_args
        self.profile_name = profile_name
        self.enqueue_for_translate = enqueue_for_translate
        self.print_raw_crisp_events = print_raw_crisp_events
        self.debug_timestamps = debug_timestamps
        self.session: aiohttp.ClientSession | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self.tasks: list[asyncio.Task[object]] = []

    async def start(self) -> None:
        if not self.remote_asr_url:
            self.state.crisp_status = "error"
            self.state.active_profile = self.profile_name
            self.state.last_error = "remote_asr_url is required when asr_mode is remote."
            await broadcast_health(self.state)
            raise ValueError(self.state.last_error)
        if not self.bearer:
            self.state.crisp_status = "error"
            self.state.active_profile = self.profile_name
            self.state.last_error = (
                f"Remote ASR bearer token is missing. Set env {self.bearer_env} "
                f"to the Colab token, or switch to a local profile."
            )
            await broadcast_health(self.state)
            raise ValueError(self.state.last_error)

        self.state.active_profile = self.profile_name
        self.state.crisp_status = "starting"
        self.state.last_error = ""
        await broadcast_health(self.state)

        headers: Mapping[str, str] = {"Authorization": f"Bearer {self.bearer}"}
        self.session = aiohttp.ClientSession(headers=headers)
        try:
            logger.info("Connecting remote ASR profile=%s url=%s", self.profile_name, self.remote_asr_url)
            self.ws = await self.session.ws_connect(self.remote_asr_url, heartbeat=20, max_msg_size=1024 * 1024)
            await self.ws.send_str(json.dumps({"type": "config", "crisp_args": self.crisp_args}))
        except Exception as exc:
            await self.session.close()
            self.session = None
            self.state.crisp_status = "error"
            self.state.last_error = f"Remote ASR connection failed: {exc}"
            await broadcast_health(self.state)
            raise

        preload = stream_step_bytes_from_extra(self.crisp_args)
        self.state.stream_preload_sec = preload / (2 * SAMPLE_RATE)
        await self.pcm_queue.put(b"\x00" * preload)

        self.tasks = [
            asyncio.create_task(self._send_pcm()),
            asyncio.create_task(self._receive_events()),
        ]
        self.state.crisp_status = "running"
        await broadcast_health(self.state)

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []
        if self.ws and not self.ws.closed:
            await self.ws.close()
        self.ws = None
        if self.session:
            await self.session.close()
        self.session = None

    async def _send_pcm(self) -> None:
        assert self.ws
        try:
            while True:
                chunk = await self.pcm_queue.get()
                try:
                    await self.ws.send_bytes(chunk)
                finally:
                    self.pcm_queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.crisp_status = "error"
            self.state.last_error = f"Remote ASR send failed: {exc}"
            await broadcast_health(self.state)

    async def _receive_events(self) -> None:
        assert self.ws
        relay = CrispEventRelay(
            self.state,
            enqueue_for_translate=self.enqueue_for_translate,
            print_raw_crisp_events=self.print_raw_crisp_events,
            debug_timestamps=self.debug_timestamps,
        )
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await relay.handle_line(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise RuntimeError(f"remote ASR websocket failed: {self.ws.exception()}")
            if self.state.crisp_status == "running":
                self.state.crisp_status = "stopped"
                self.state.last_error = "Remote ASR websocket closed."
                await broadcast_health(self.state)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.crisp_status = "error"
            self.state.last_error = f"Remote ASR receive failed: {exc}"
            await broadcast_health(self.state)
