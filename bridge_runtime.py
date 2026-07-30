from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import aiohttp
from aiohttp import web

from asr_backend import LocalCrispAsrBackend, RemoteCrispAsrBackend
from bridge_config import BridgeRunConfig, load_bridge_config_file, parse_args, run_config_from_ns
from bridge_state import BridgeRealtimeState, broadcast_health
from translation import (
    load_merged_glossary,
    resolve_translation_system_prompt,
    translate_health_url,
    translator_health_monitor,
    translator_worker,
)
from web_app import make_app

logger = logging.getLogger(__name__)


class CrispRuntime:
    def __init__(self, state: BridgeRealtimeState, pcm_queue: asyncio.Queue[bytes]) -> None:
        self.state = state
        self.pcm_queue = pcm_queue
        self.asr_backend: LocalCrispAsrBackend | RemoteCrispAsrBackend | None = None
        self.http_session: aiohttp.ClientSession | None = None
        self.tasks: list[asyncio.Task[object]] = []
        self.lock = asyncio.Lock()

    async def start(self, cfg: BridgeRunConfig) -> None:
        async with self.lock:
            await self._stop_locked()
            self._drain_pcm_queue()

            self.state.active_profile = cfg.profile_name
            self.state.crisp_status = "starting"
            self.state.last_error = ""
            self.state.translator_status = "checking" if cfg.translate_enabled else "disabled"
            await broadcast_health(self.state)

            common = dict(
                state=self.state,
                pcm_queue=self.pcm_queue,
                crisp_args=cfg.crisp_args,
                profile_name=cfg.profile_name,
                enqueue_for_translate=cfg.translate_enabled,
                print_raw_crisp_events=cfg.print_raw_crisp_events,
                debug_timestamps=cfg.debug_timestamps,
            )
            if cfg.asr_mode == "remote":
                self.asr_backend = RemoteCrispAsrBackend(
                    remote_asr_url=cfg.remote_asr_url,
                    bearer=cfg.remote_asr_bearer,
                    bearer_env=cfg.remote_asr_bearer_env,
                    **common,
                )
            else:
                self.asr_backend = LocalCrispAsrBackend(
                    crisp_exe=cfg.crisp_exe,
                    crisp_hide_stderr=cfg.crisp_hide_stderr,
                    verbose=cfg.verbose,
                    warmup_sec=cfg.warmup_sec,
                    warmup_audio=cfg.warmup_audio,
                    **common,
                )
            try:
                await self.asr_backend.start()
            except Exception:
                await self.asr_backend.stop()
                self.asr_backend = None
                raise

            if cfg.translate_enabled:
                assert cfg.system_prompt is not None
                assert cfg.glossary is not None
                self.http_session = aiohttp.ClientSession()
                self.tasks.append(
                    asyncio.create_task(
                        translator_health_monitor(
                            self.state,
                            self.http_session,
                            health_url=translate_health_url(cfg.translate_url),
                            bearer=cfg.translate_bearer,
                        )
                    )
                )
                self.tasks.append(
                    asyncio.create_task(
                        translator_worker(
                            self.state.transcript_queue,
                            self.http_session,
                            state=self.state,
                            translate_url=cfg.translate_url,
                            translate_model=cfg.translate_model,
                            translate_window=cfg.translate_window,
                            translate_temperature=cfg.translate_temperature,
                            translate_top_k=cfg.translate_top_k,
                            translate_top_p=cfg.translate_top_p,
                            translate_repeat_penalty=cfg.translate_repeat_penalty,
                            translate_max_tokens=cfg.translate_max_tokens,
                            system_prompt=cfg.system_prompt,
                            glossary=cfg.glossary,
                            bearer=cfg.translate_bearer,
                            ws_clients=self.state.ws_clients,
                        )
                    )
                )

            await broadcast_health(self.state)

    async def stop(self) -> None:
        async with self.lock:
            await self._stop_locked()
            await broadcast_health(self.state)

    async def _stop_locked(self) -> None:
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks = []

        if self.asr_backend:
            await self.asr_backend.stop()
        self.asr_backend = None

        if self.http_session:
            await self.http_session.close()
        self.http_session = None
        self.state.crisp_status = "stopped"

    def _drain_pcm_queue(self) -> None:
        while True:
            try:
                self.pcm_queue.get_nowait()
                self.pcm_queue.task_done()
            except asyncio.QueueEmpty:
                return


def discover_profiles(profiles_dir: Path) -> list[dict[str, object]]:
    profiles: list[dict[str, object]] = []
    local_profile_names = {path.name for path in profiles_dir.glob("*.json") if ".example." not in path.name}
    for path in sorted(profiles_dir.glob("*.json")):
        if ".example." in path.name:
            local_name = path.name.replace(".example.", ".")
            if local_name in local_profile_names:
                continue
        try:
            data = load_bridge_config_file(str(path))
        except SystemExit:
            continue
        if not isinstance(data.get("crisp_args"), list):
            continue
        profiles.append(
            {
                "name": path.name,
                "label": str(data.get("name") or path.stem),
                "description": str(data.get("description") or ""),
            }
        )
    return profiles


def resolve_profile_path(profiles_dir: Path, name: str) -> Path:
    candidate = Path(name)
    if candidate.is_absolute():
        path = candidate
    else:
        path = profiles_dir / candidate.name
    path = path.resolve()
    if path.parent != profiles_dir.resolve() or path.suffix.lower() != ".json" or not path.is_file():
        raise ValueError(f"Unknown profile: {name}")
    return path


def config_from_profile(path: Path) -> BridgeRunConfig:
    ns, crisp_args = parse_args(["bridge_server.py", "--config", str(path)])
    cfg = run_config_from_ns(ns, crisp_args, profile_name=path.name)
    if cfg.translate_enabled:
        cfg.glossary = load_merged_glossary((ns.glossary_file or "").strip() or None)
        cfg.system_prompt = resolve_translation_system_prompt(
            (ns.translate_prompt_file or "").strip() or None,
            cfg.glossary,
        )
    return cfg


async def async_main(cfg: BridgeRunConfig, host: str, port: int) -> None:
    pcm_queue: asyncio.Queue[bytes] = asyncio.Queue()
    bridge_state = BridgeRealtimeState(transcript_queue=asyncio.Queue())
    runtime = CrispRuntime(bridge_state, pcm_queue)
    profiles_dir = Path(__file__).resolve().parent / "profiles"

    async def list_profiles() -> dict[str, object]:
        return {
            "profiles": discover_profiles(profiles_dir),
            "active": bridge_state.active_profile,
            "crisp_status": bridge_state.crisp_status,
        }

    async def select_profile(name: str) -> dict[str, object]:
        path = resolve_profile_path(profiles_dir, name)
        try:
            await runtime.start(config_from_profile(path))
        except Exception as exc:  # noqa: BLE001
            logger.error("Profile start failed: %s", exc)
            if not bridge_state.last_error:
                bridge_state.last_error = str(exc)
            bridge_state.crisp_status = "error"
        return {
            "profiles": discover_profiles(profiles_dir),
            "active": bridge_state.active_profile,
            "crisp_status": bridge_state.crisp_status,
        }

    if cfg.crisp_args:
        try:
            await runtime.start(cfg)
        except Exception as exc:  # noqa: BLE001
            # Keep UI up so user can switch profile or fix env (e.g. missing remote token).
            logger.error("Initial profile start failed: %s", exc)
            if not bridge_state.last_error:
                bridge_state.last_error = str(exc)
            bridge_state.crisp_status = "error"
            bridge_state.active_profile = cfg.profile_name
    else:
        bridge_state.crisp_status = "stopped"
        bridge_state.translator_status = "disabled"
        bridge_state.last_error = "Select a profile before starting capture."

    runner = web.AppRunner(
        make_app(
            pcm_queue,
            bridge_state,
            list_profiles=list_profiles,
            select_profile=select_profile,
        )
    )
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    logger.info("Serving http://%s:%s/ - select a profile, allow capture, then wait for SDP.", host, port)

    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Shutting down (KeyboardInterrupt)...")
    finally:
        await runtime.stop()
        await runner.cleanup()
