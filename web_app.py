from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Mapping

import av
from aiohttp import WSMsgType, web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription

from bridge_state import BridgeRealtimeState, broadcast_health
from crisp_process import SAMPLE_RATE
from overlay_page import obs_overlay_html

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).with_name("static")
CONTROL_HTML = STATIC_DIR / "index.html"
OVERLAY_SCRIPT = Path(__file__).with_name("subtitle_overlay_qt.py")


def drain_pcm_queue(pcm_queue: asyncio.Queue[bytes]) -> None:
    while True:
        try:
            pcm_queue.get_nowait()
            pcm_queue.task_done()
        except asyncio.QueueEmpty:
            return


async def consume_track(
    track: MediaStreamTrack,
    pcm_queue: asyncio.Queue[bytes],
    state: BridgeRealtimeState,
) -> None:
    resampler = av.audio.resampler.AudioResampler(
        format="s16",
        layout="mono",
        rate=SAMPLE_RATE,
    )
    try:
        while True:
            frame = await track.recv()
            for out in resampler.resample(frame):
                arr = out.to_ndarray()
                # s16 planar: shape (channels, samples)
                pcm = arr[0].tobytes() if arr.ndim == 2 else arr.astype("<i2", copy=False).tobytes()
                if pcm and state.first_pcm_mono is None:
                    state.first_pcm_mono = time.monotonic()
                await pcm_queue.put(pcm)
    except Exception as exc:  # noqa: BLE001
        logger.warning("audio track ended: %s", exc)


def make_app(
    pcm_queue: asyncio.Queue[bytes],
    state: BridgeRealtimeState,
    *,
    list_profiles: Callable[[], Awaitable[dict[str, object]]],
    select_profile: Callable[
        [str, dict[str, str] | None, dict[str, str] | None], Awaitable[dict[str, object]]
    ],
) -> web.Application:
    pcs: set[RTCPeerConnection] = set()
    offer_lock = asyncio.Lock()
    overlay_process: subprocess.Popen[bytes] | None = None

    async def index(_: web.Request) -> web.Response:
        if not CONTROL_HTML.is_file():
            return web.Response(status=503, text=f"Missing UI file: {CONTROL_HTML}")
        return web.FileResponse(CONTROL_HTML)

    async def diagnostics(_: web.Request) -> web.Response:
        diag = STATIC_DIR / "diagnostics.html"
        if not diag.is_file():
            return web.Response(status=503, text="Diagnostics page not found")
        return web.FileResponse(diag)

    def _overlay_num(query: Mapping[str, str], name: str, default: float, lo: float, hi: float) -> float:
        try:
            value = float(query.get(name, default))
        except (TypeError, ValueError):
            return default
        return min(hi, max(lo, value))

    async def obs_overlay(req: web.Request) -> web.Response:
        ws_proto = "wss" if req.secure else "ws"
        q = req.query
        mode = q.get("mode", state.overlay_mode)
        if mode not in ("source", "trans", "both"):
            mode = "both"
        pos = q.get("pos", "bottom")
        if pos not in ("top", "bottom"):
            pos = "bottom"
        return web.Response(
            text=obs_overlay_html(
                f"{ws_proto}://{req.host}/ws",
                mode=mode,
                hold_sec=_overlay_num(q, "hold", 2.0, 0.5, 30.0),
                fade_sec=_overlay_num(q, "fade", 4.0, 0.0, 300.0),
                font=_overlay_num(q, "font", 1.0, 0.5, 4.0),
                pos=pos,
                demo=q.get("demo") == "1",
                interj_len=int(_overlay_num(q, "interj_len", state.overlay_interj_len, 0.0, 10.0)),
                interj_ratio=_overlay_num(q, "interj_ratio", state.overlay_interj_ratio, 0.05, 1.0),
                interj_gap_sec=_overlay_num(q, "interj_gap", state.overlay_interj_gap_sec, 0.0, 30.0),
            ),
            content_type="text/html",
        )

    async def offer(req: web.Request) -> web.Response:
        async with offer_lock:
            dead = {p for p in pcs if p.connectionState in ("closed", "failed")}
            for p in dead:
                pcs.discard(p)

            busy = [p for p in pcs if p.connectionState not in ("closed", "failed")]
            if busy:
                msg = f"WebRTC offer rejected: a session is already active (state={busy[0].connectionState})"
                logger.warning("%s", msg)
                state.last_error = msg
                await broadcast_health(state)
                return web.json_response(
                    {
                        "error": "only one browser session is allowed; close the other tab or wait for disconnect.",
                    },
                    status=409,
                )
            if state.crisp_status != "running":
                msg = "WebRTC offer rejected: select a running profile before capture."
                logger.warning("%s", msg)
                state.last_error = msg
                await broadcast_health(state)
                return web.json_response({"error": msg}, status=409)

            try:
                params = await req.json()
            except json.JSONDecodeError:
                return web.json_response(
                    {"error": "Expected a JSON body with 'sdp' and 'type'."}, status=400
                )
            if not isinstance(params, dict) or not params.get("sdp") or not params.get("type"):
                return web.json_response(
                    {"error": "Body must be a JSON object with non-empty 'sdp' and 'type'."},
                    status=400,
                )

            pc = RTCPeerConnection()
            pcs.add(pc)

            @pc.on("connectionstatechange")
            async def _on_state_change() -> None:
                logger.info("pc connectionState=%s", pc.connectionState)
                if pc.connectionState not in ("failed", "closed"):
                    return
                if pc.connectionState == "failed":
                    await pc.close()
                pcs.discard(pc)
                drain_pcm_queue(pcm_queue)
                state.first_pcm_mono = None
                state.last_audio_t = None
                if not any(p.connectionState not in ("closed", "failed") for p in pcs):
                    state.last_error = "" if pc.connectionState == "closed" else "WebRTC session ended."
                    await broadcast_health(state)

            @pc.on("track")
            def _on_track(track: MediaStreamTrack) -> None:
                logger.info("track received kind=%s", track.kind)
                if track.kind != "audio":
                    return

                state.first_pcm_mono = None
                state.last_audio_t = None
                asyncio.create_task(consume_track(track, pcm_queue, state))

            remote = RTCSessionDescription(sdp=params["sdp"], type=params["type"])
            await pc.setRemoteDescription(remote)
            ans = await pc.createAnswer()
            await pc.setLocalDescription(ans)

            return web.Response(
                content_type="application/json",
                text=json.dumps({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}),
            )

    async def ws_handler(req: web.Request) -> web.StreamResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(req)
        state.ws_clients.add(ws)
        logger.info("WebSocket /ws connected (%d clients)", len(state.ws_clients))
        await broadcast_health(state)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    logger.debug("ws connection error: %s", ws.exception())
                    break
                # Ignore client text/binary; server pushes transcript + translation.
        finally:
            state.ws_clients.discard(ws)
            logger.info("WebSocket /ws disconnected (%d clients)", len(state.ws_clients))
        return ws

    async def profiles_handler(_: web.Request) -> web.Response:
        return web.json_response(await list_profiles())

    async def select_profile_handler(req: web.Request) -> web.Response:
        try:
            data = await req.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Expected JSON body."}, status=400)
        name = str(data.get("name") or "").strip() if isinstance(data, dict) else ""
        if not name:
            return web.json_response({"error": "Missing profile name."}, status=400)
        asr_source = data.get("asr_source") if isinstance(data, dict) and isinstance(data.get("asr_source"), dict) else None
        translate_source = (
            data.get("translate_source")
            if isinstance(data, dict) and isinstance(data.get("translate_source"), dict)
            else None
        )
        try:
            result = await select_profile(name, asr_source, translate_source)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=404)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to select profile")
            return web.json_response({"error": str(exc)}, status=500)
        return web.json_response(result)

    async def start_overlay(req: web.Request) -> web.Response:
        nonlocal overlay_process
        if overlay_process and overlay_process.poll() is None:
            return web.json_response({"status": "already_running", "pid": overlay_process.pid})
        if not OVERLAY_SCRIPT.is_file():
            return web.json_response(
                {"error": f"Overlay script not found: {OVERLAY_SCRIPT}"},
                status=503,
            )

        ws_proto = "wss" if req.secure else "ws"
        ws_url = f"{ws_proto}://{req.host}/ws"
        cmd = [sys.executable, str(OVERLAY_SCRIPT), "--ws-url", ws_url]
        try:
            overlay_process = subprocess.Popen(cmd, cwd=str(OVERLAY_SCRIPT.parent))
        except OSError as exc:
            logger.exception("Failed to start subtitle overlay")
            return web.json_response({"error": str(exc)}, status=500)

        logger.info("Subtitle overlay started pid=%s ws=%s", overlay_process.pid, ws_url)
        return web.json_response({"status": "started", "pid": overlay_process.pid})

    async def stop_overlay(_req: web.Request) -> web.Response:
        nonlocal overlay_process
        proc = overlay_process
        running = proc is not None and proc.poll() is None
        if running:
            assert proc is not None
            proc.terminate()
            logger.info("Subtitle overlay stopped pid=%s", proc.pid)
        overlay_process = None
        return web.json_response({"status": "stopped" if running else "not_running"})

    async def overlay_status(_req: web.Request) -> web.Response:
        nonlocal overlay_process
        proc = overlay_process
        if proc is None or proc.poll() is not None:
            return web.json_response({"running": False, "pid": None})
        return web.json_response({"running": True, "pid": proc.pid})

    async def cleanup(_app: web.Application) -> None:
        if overlay_process and overlay_process.poll() is None:
            overlay_process.terminate()
        coros = [pc.close() for pc in list(pcs)]
        await asyncio.gather(*coros, return_exceptions=True)
        pcs.clear()

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/diagnostics", diagnostics)
    if STATIC_DIR.is_dir():
        app.router.add_static("/static/", STATIC_DIR, name="static")
    app.router.add_get("/obs-overlay", obs_overlay)
    app.router.add_post("/offer", offer)
    app.router.add_post("/overlay/start", start_overlay)
    app.router.add_post("/overlay/stop", stop_overlay)
    app.router.add_get("/overlay/status", overlay_status)
    app.router.add_get("/profiles", profiles_handler)
    app.router.add_post("/profiles/select", select_profile_handler)
    app.router.add_get("/ws", ws_handler)
    app.on_cleanup.append(cleanup)
    return app
