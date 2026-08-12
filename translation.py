from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from collections import deque
from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from aiohttp import web

from bridge_state import BridgeRealtimeState, broadcast_health, broadcast_json

logger = logging.getLogger(__name__)

def build_glossary_text(glossary: dict[str, str]) -> str:
    if not glossary:
        return ""
    lines = "\n".join(f"- {k} => {v}" for k, v in glossary.items())
    return f"術語表（必須固定使用以下譯法）：\n{lines}"


def clean_translation_output(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(r"</?\s*source\s*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"</?\s*translation\s*>", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("譯文：", "").replace("译文：", "").strip()
    return cleaned


def build_user_message(
    text: str,
    glossary: dict[str, str],
    target_lang: str = "繁體中文（台灣）",
    history: Sequence[tuple[str, str]] | None = None,
) -> str:
    context_blocks: list[str] = []
    if glossary:
        context_blocks.append(build_glossary_text(glossary))
    if history:
        history_lines = [
            f"{idx}. 原文：{orig}\n   译文：{trans}" for idx, (orig, trans) in enumerate(history, start=1)
        ]
        context_blocks.append(
            "上文参考（只用于理解语气、人物、代词和场景，不要重新翻译）：\n" + "\n".join(history_lines)
        )
    prefix = ("\n\n".join(context_blocks) + "\n\n") if context_blocks else ""
    return (
        f"{prefix}"
        f"把【当前原文】翻译为{target_lang}。只输出译文，不要输出标签、原文、解释或额外内容。\n\n"
        f"【当前原文】\n{text}"
    )


def load_merged_glossary(glossary_file: str | None) -> dict[str, str]:
    if not glossary_file or not str(glossary_file).strip():
        return {}
    pth = os.path.expanduser(glossary_file.strip())
    if not os.path.isfile(pth):
        logger.error("Glossary file not found: %s", pth)
        raise SystemExit(2)
    with open(pth, encoding="utf-8") as f:
        loaded = json.load(f)
    if not isinstance(loaded, dict):
        logger.error("Glossary file must be a JSON object: %s", pth)
        raise SystemExit(2)
    return {str(k): v for k, v in loaded.items() if isinstance(k, str) and isinstance(v, str)}


def resolve_translation_system_prompt(
    translate_prompt_file: str | None,
    glossary: dict[str, str] | None = None,
) -> str:
    # ponytail: HY-MT wants instruction in user msg; empty system is intentional
    del glossary
    if not translate_prompt_file or not str(translate_prompt_file).strip():
        return ""
    pth = os.path.expanduser(translate_prompt_file.strip())
    if not os.path.isfile(pth):
        logger.error("Translation prompt file not found: %s", pth)
        raise SystemExit(2)
    with open(pth, encoding="utf-8") as f:
        return f.read().strip()


def translate_health_url(translate_url: str) -> str:
    parts = urlsplit(translate_url)
    return urlunsplit((parts.scheme or "http", parts.netloc, "/health", "", ""))


async def translator_health_monitor(
    state: BridgeRealtimeState,
    session: aiohttp.ClientSession,
    *,
    health_url: str,
    bearer: str | None = None,
    interval_sec: float = 3.0,
) -> None:
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else None
    while True:
        try:
            async with session.get(health_url, headers=headers, timeout=aiohttp.ClientTimeout(total=2.0)) as resp:
                body = await resp.text()
                if 200 <= resp.status < 300:
                    state.translator_status = "online"
                    if (
                        state.last_error.startswith("llama-server health check failed")
                        or state.last_error.startswith("llama-server loading model")
                    ):
                        state.last_error = ""
                else:
                    msg = ""
                    try:
                        data = json.loads(body) if body else {}
                        err = data.get("error", {}) if isinstance(data, dict) else {}
                        if isinstance(err, dict):
                            msg = str(err.get("message") or err.get("code") or "").strip()
                    except json.JSONDecodeError:
                        msg = body[:120].strip()

                    if resp.status == 503 and "loading" in msg.lower():
                        state.translator_status = "checking"
                        state.last_error = f"llama-server loading model: {msg or 'HTTP 503'}"
                    else:
                        state.translator_status = "offline"
                        detail = f": {msg}" if msg else ""
                        state.last_error = f"llama-server health check failed: HTTP {resp.status}{detail}"
        except asyncio.CancelledError:
            raise
        except aiohttp.ClientConnectorError as ex:
            state.translator_status = "offline"
            state.last_error = f"llama-server connection refused: {ex}"
        except TimeoutError:
            state.translator_status = "offline"
            state.last_error = "llama-server health check timeout"
        except Exception as ex:  # noqa: BLE001
            state.translator_status = "offline"
            state.last_error = f"llama-server health check failed: {ex}"

        await broadcast_health(state)
        await asyncio.sleep(interval_sec)


async def _report_translate_error(
    state: BridgeRealtimeState,
    ws_clients: set[web.WebSocketResponse],
    transcript_queue: asyncio.Queue[tuple[int, str]],
    *,
    seq: int,
    msg: str,
    status: str = "error",
) -> None:
    logger.warning("%s", msg)
    state.translator_status = status
    state.last_error = msg
    await broadcast_json(ws_clients, {"type": "translation_error", "seq": seq, "message": msg})
    transcript_queue.task_done()
    await broadcast_health(state)


async def translator_worker(
    transcript_queue: asyncio.Queue[tuple[int, str]],
    session: aiohttp.ClientSession,
    *,
    state: BridgeRealtimeState,
    translate_url: str,
    translate_model: str,
    translate_window: int,
    translate_temperature: float,
    translate_top_k: int,
    translate_top_p: float,
    translate_repeat_penalty: float,
    translate_max_tokens: int,
    system_prompt: str,
    glossary: dict[str, str],
    bearer: str | None,
    ws_clients: set[web.WebSocketResponse],
) -> None:
    context_items = max(1, translate_window)
    history: deque[tuple[str, str]] = deque(maxlen=max(12, context_items * 4))
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    state.translator_status = "checking"
    state.translation_queue_size = transcript_queue.qsize()
    await broadcast_health(state)

    while True:
        seq, text = await transcript_queue.get()
        await broadcast_health(state)
        stripped = text.strip()
        if not stripped:
            transcript_queue.task_done()
            await broadcast_health(state)
            continue
        messages: list[dict[str, str]] = []
        if system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append(
            {
                "role": "user",
                "content": build_user_message(
                    stripped, glossary, history=list(history)[-context_items:]
                ),
            }
        )
        payload = {
            "model": translate_model,
            "messages": messages,
            "temperature": translate_temperature,
            "top_k": translate_top_k,
            "top_p": translate_top_p,
            "repeat_penalty": translate_repeat_penalty,
            "max_tokens": translate_max_tokens,
            "stream": False,
        }
        try:
            async with session.post(
                translate_url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    short_err = (body[:240] if body else "") or resp.reason
                    await _report_translate_error(
                        state,
                        ws_clients,
                        transcript_queue,
                        seq=seq,
                        msg=f"translate HTTP {resp.status}: {short_err}",
                    )
                    continue
                try:
                    data = json.loads(body)
                    result = clean_translation_output(data["choices"][0]["message"]["content"] or "")
                except (json.JSONDecodeError, KeyError, IndexError, TypeError) as ex:
                    logger.warning("translate parse error body=%s", body[:120])
                    await _report_translate_error(
                        state,
                        ws_clients,
                        transcript_queue,
                        seq=seq,
                        msg=f"translate parse error: {ex}",
                    )
                    continue
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            await _report_translate_error(
                state, ws_clients, transcript_queue, seq=seq, msg="translation timeout", status="offline"
            )
            continue
        except aiohttp.ClientConnectorError as ex:
            await _report_translate_error(
                state,
                ws_clients,
                transcript_queue,
                seq=seq,
                msg=f"llama-server connection refused: {ex}",
                status="offline",
            )
            continue
        except Exception as ex:  # noqa: BLE001
            await _report_translate_error(
                state,
                ws_clients,
                transcript_queue,
                seq=seq,
                msg=f"translate request failed: {ex}",
            )
            continue

        history.append((stripped, result))
        state.translator_status = "online"
        state.last_error = ""
        await broadcast_json(ws_clients, {"type": "translation", "seq": seq, "text": result})
        transcript_queue.task_done()
        await broadcast_health(state)
