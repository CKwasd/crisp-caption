from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import dataclass

from crisp_process import normalize_crisp_argv

logger = logging.getLogger(__name__)

ARGPARSE_DESCRIPTION = "WebRTC browser audio bridge for CrispASR streaming ASR and optional translation."


def strip_jsonc(text: str) -> str:
    """Remove JSONC comments (``//`` and ``/* ... */``) but keep string content.

    Profile files are JSONC so they can carry comments for humans. Standard
    ``json.load`` rejects comments, so we strip them before parsing. We scan
    character by character so ``//`` inside a string (e.g. ``https://...``)
    is preserved.
    """
    out: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    string_quote = ""
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(nxt)
                i += 2
                continue
            if ch == string_quote:
                in_string = False
            i += 1
            continue
        # Not in a string: handle comments.
        if ch == '"' or ch == "'":
            in_string = True
            string_quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            # line comment
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            # block comment
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def load_jsonc_file(path: str) -> dict[str, object]:
    """Load a JSONC profile file and return its JSON object.

    Raises SystemExit(2) on missing file, and lets json.JSONDecodeError bubble
    up for callers that want to format the message.
    """
    pth = os.path.expanduser(path)
    if not os.path.isfile(pth):
        logger.error("Bridge config file not found: %s", pth)
        raise SystemExit(2)
    with open(pth, encoding="utf-8") as f:
        text = f.read()
    data = json.loads(strip_jsonc(text))
    if not isinstance(data, dict):
        logger.error("Bridge config must be a JSON object: %s", path)
        raise SystemExit(2)
    return data

DEFAULT_TRANSLATE_URL = os.environ.get(
    "CRISPASR_TRANSLATE_URL",
    "http://127.0.0.1:8080/v1/chat/completions",
)


@dataclass
class BridgeRunConfig:
    crisp_exe: str
    crisp_args: list[str]
    asr_mode: str = "local"
    remote_asr_url: str = ""
    remote_asr_bearer: str | None = None
    remote_asr_bearer_env: str = "CRISPASR_REMOTE_KEY"
    profile_name: str = ""
    crisp_hide_stderr: bool = False
    verbose: bool = False
    translate_enabled: bool = False
    translate_url: str = DEFAULT_TRANSLATE_URL
    translate_model: str = ""
    translate_window: int = 6
    translate_temperature: float = 0.7
    translate_top_k: int = 20
    translate_top_p: float = 0.6
    translate_repeat_penalty: float = 1.05
    translate_max_tokens: int = 256
    print_raw_crisp_events: bool = False
    debug_timestamps: bool = False
    translate_bearer: str | None = None
    system_prompt: str | None = None
    glossary: dict[str, str] | None = None
    overlay_interj_len: int = 3
    overlay_interj_ratio: float = 0.4
    overlay_interj_gap_sec: float = 2.0
    overlay_mode: str = "both"

CRISP_PATH_VALUE_FLAGS = frozenset({"-m", "-vm", "--model", "--vad-model", "--punc-model"})


BRIDGE_CONFIG_KEYS = frozenset(
    {
        "host",
        "port",
        "asr_mode",
        "remote_asr_url",
        "remote_asr_bearer_env",
        "crispasr",
        "crisp_hide_stderr",
        "verbose",
        "translate_url",
        "translate_model",
        "translate_window",
        "translate_temperature",
        "translate_top_k",
        "translate_top_p",
        "translate_repeat_penalty",
        "translate_max_tokens",
        "temperature",
        "top_k",
        "top_p",
        "repeat_penalty",
        "max_tokens",
        "print_raw_crisp_events",
        "debug_timestamps",
        "overlay_interj_len",
        "overlay_interj_ratio",
        "overlay_interj_gap_sec",
        "overlay_mode",
        "no_translate",
        "translate_prompt_file",
        "glossary_file",
        "crisp_args",
        "name",
        "description",
        "tags",
    }
)


def pop_config_arg(argv: list[str]) -> tuple[str | None, list[str]]:
    out: list[str] = []
    i = 0
    config_path: str | None = None
    while i < len(argv):
        if argv[i] in ("--config", "-c"):
            if i + 1 >= len(argv):
                raise SystemExit("error: option --config requires a path argument")
            config_path = argv[i + 1]
            i += 2
            continue
        out.append(argv[i])
        i += 1
    return config_path, out


def load_bridge_config_file(path: str) -> dict[str, object]:
    data = load_jsonc_file(path)
    bad = set(data) - BRIDGE_CONFIG_KEYS
    if bad:
        logger.warning("Ignoring unknown keys in bridge config: %s", ", ".join(sorted(bad)))
    return data


def resolve_config_crisp_paths(tokens: list[str], config_path: str | None) -> list[str]:
    if not config_path:
        return tokens
    base_dir = os.path.dirname(os.path.abspath(os.path.expanduser(config_path)))
    resolved = list(tokens)
    for idx, token in enumerate(resolved[:-1]):
        if token not in CRISP_PATH_VALUE_FLAGS:
            continue
        value = resolved[idx + 1]
        if not value or os.path.isabs(value) or "://" in value:
            continue
        resolved[idx + 1] = os.path.normpath(os.path.join(base_dir, value))
    return resolved


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    argv = argv[1:]
    if "--" in argv:
        idx = argv.index("--")
        main_argv = argv[:idx]
        crisp_argv = argv[idx + 1 :]
    else:
        main_argv = argv
        crisp_argv = []

    crisp_argv = [a for a in crisp_argv if a != "--"]

    config_path, main_argv = pop_config_arg(main_argv)
    cfg: dict[str, object] = {}
    if config_path:
        cfg = load_bridge_config_file(config_path)

    crisp_from_cfg = cfg.get("crisp_args")
    defaults = {k: cfg[k] for k in BRIDGE_CONFIG_KEYS if k in cfg and k != "crisp_args"}
    translate_sampling_aliases = {
        "temperature": "translate_temperature",
        "top_k": "translate_top_k",
        "top_p": "translate_top_p",
        "repeat_penalty": "translate_repeat_penalty",
        "max_tokens": "translate_max_tokens",
    }
    for src, dst in translate_sampling_aliases.items():
        if src in defaults and dst not in defaults:
            defaults[dst] = defaults[src]
    for bkey in (
        "crisp_hide_stderr",
        "verbose",
        "no_translate",
        "print_raw_crisp_events",
        "debug_timestamps",
    ):
        if bkey in defaults and not isinstance(defaults[bkey], bool):
            del defaults[bkey]

    p = argparse.ArgumentParser(description=ARGPARSE_DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter)

    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument(
        "--asr-mode",
        choices=("local", "remote"),
        default="local",
        help="ASR backend mode: local CrispASR subprocess or remote WebSocket ASR service.",
    )
    p.add_argument(
        "--remote-asr-url",
        default="",
        help="Remote ASR WebSocket URL, for example wss://example.trycloudflare.com/asr/stream.",
    )
    p.add_argument(
        "--remote-asr-bearer-env",
        default="CRISPASR_REMOTE_KEY",
        help="Environment variable containing the Bearer token for remote ASR.",
    )
    p.add_argument(
        "--crispasr",
        default=os.environ.get("CRISPASR_EXE", "crispasr"),
        help="crispasr executable (PATH or CRISPASR_EXE env)",
    )

    p.add_argument(
        "--crisp-hide-stderr",
        action="store_true",
        help="Discard CrispASR stderr entirely (default: forwarded at DEBUG; use -v for INFO diagnostics)",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose: ICE (aioice) DEBUG, aiohttp access, aiortc; also CrispASR stderr at INFO (VAD, Vulkan)",
    )
    p.add_argument(
        "--print-raw-crisp-events",
        action="store_true",
        help="Print raw CrispASR stream-json events on stdout while still broadcasting bridge transcript events to /ws.",
    )
    p.add_argument(
        "--debug-timestamps",
        action="store_true",
        help="Add bridge wall-clock/backlog timing fields to terminal transcript JSON for latency debugging.",
    )

    p.add_argument(
        "--translate-url",
        default=DEFAULT_TRANSLATE_URL,
        help="OpenAI-compatible chat completions URL "
        "(default env CRISPASR_TRANSLATE_URL or http://127.0.0.1:8080/v1/chat/completions)",
    )
    p.add_argument(
        "--translate-model",
        default="",
        metavar="MODEL",
        help="Enable translation worker when non-empty (e.g. HY-MT). Ignored with --no-translate.",
    )
    p.add_argument(
        "--translate-window",
        type=int,
        default=6,
        help="Sliding window of recent (source, translated) pairs in the prompt (default 6)",
    )
    p.add_argument(
        "--translate-temperature",
        type=float,
        default=0.7,
        help="Translation sampling temperature (default 0.7).",
    )
    p.add_argument(
        "--translate-top-k",
        type=int,
        default=20,
        help="Translation top-k sampling value (default 20).",
    )
    p.add_argument(
        "--translate-top-p",
        type=float,
        default=0.6,
        help="Translation top-p sampling value (default 0.6).",
    )
    p.add_argument(
        "--translate-repeat-penalty",
        type=float,
        default=1.05,
        help="Translation repeat penalty / repetition penalty (default 1.05).",
    )
    p.add_argument(
        "--translate-max-tokens",
        type=int,
        default=4096,
        help="Maximum number of tokens generated per translation request (default 4096).",
    )
    p.add_argument(
        "--translate-prompt-file",
        default="",
        metavar="PATH",
        help="UTF-8 text file for translation system prompt (glossary is injected into current user message).",
    )
    p.add_argument(
        "--glossary-file",
        default="",
        metavar="PATH",
        help='JSON object {"source":"translation", ...}; terms come only from this file (omit for no glossary).',
    )
    p.add_argument(
        "--no-translate",
        action="store_true",
        help="Disable translation worker (WebSocket still receives transcripts only)",
    )
    p.add_argument(
        "--overlay-interj-len",
        type=int,
        default=3,
        help="Overlay: max chars of a trailing final that gets merged into the current sentence (default 3).",
    )
    p.add_argument(
        "--overlay-interj-ratio",
        type=float,
        default=0.4,
        help="Overlay: merge threshold as ratio of the previous final length (default 0.4).",
    )
    p.add_argument(
        "--overlay-interj-gap",
        dest="overlay_interj_gap_sec",
        type=float,
        default=2.0,
        help="Overlay: max seconds between finals for interjection merge (default 2.0).",
    )
    p.add_argument(
        "--overlay-mode",
        choices=("source", "trans", "both"),
        default="both",
        help="Overlay display mode: source only, translation only, or both (default both).",
    )
    p.set_defaults(**defaults)

    cli_crisp = normalize_crisp_argv(crisp_argv)

    ns = p.parse_args(main_argv)
    setattr(ns, "bridge_config_path", config_path)

    cfg_crisp: list[str] = []
    if isinstance(crisp_from_cfg, list):
        cfg_crisp = normalize_crisp_argv([str(x) for x in crisp_from_cfg])
        if str(cfg.get("asr_mode") or "local").strip().lower() != "remote":
            cfg_crisp = resolve_config_crisp_paths(cfg_crisp, config_path)

    # Config crisp_args is the base; optional `-- ...` appends (later tokens override in typical CLIs).
    if cfg_crisp and cli_crisp:
        crisp_argv = cfg_crisp + cli_crisp
    elif cfg_crisp:
        crisp_argv = cfg_crisp
    else:
        crisp_argv = cli_crisp

    return ns, crisp_argv


def run_config_from_ns(
    ns: argparse.Namespace,
    crisp_args: list[str],
    *,
    profile_name: str = "",
    system_prompt: str | None = None,
    glossary: dict[str, str] | None = None,
    translate_bearer: str | None = None,
    remote_asr_bearer: str | None = None,
) -> BridgeRunConfig:
    translate_enabled = not ns.no_translate and bool((ns.translate_model or "").strip())
    return BridgeRunConfig(
        crisp_exe=ns.crispasr,
        crisp_args=crisp_args,
        asr_mode=ns.asr_mode,
        remote_asr_url=ns.remote_asr_url,
        remote_asr_bearer_env=(ns.remote_asr_bearer_env or "CRISPASR_REMOTE_KEY"),
        remote_asr_bearer=remote_asr_bearer
        if remote_asr_bearer is not None
        else (os.environ.get(ns.remote_asr_bearer_env or "CRISPASR_REMOTE_KEY") or None),
        profile_name=profile_name,
        crisp_hide_stderr=ns.crisp_hide_stderr,
        verbose=ns.verbose,
        translate_enabled=translate_enabled,
        translate_url=ns.translate_url,
        translate_model=(ns.translate_model or "").strip(),
        translate_window=ns.translate_window,
        translate_temperature=ns.translate_temperature,
        translate_top_k=ns.translate_top_k,
        translate_top_p=ns.translate_top_p,
        translate_repeat_penalty=ns.translate_repeat_penalty,
        translate_max_tokens=ns.translate_max_tokens,
        print_raw_crisp_events=ns.print_raw_crisp_events,
        debug_timestamps=ns.debug_timestamps,
        overlay_interj_len=int(ns.overlay_interj_len),
        overlay_interj_ratio=float(ns.overlay_interj_ratio),
        overlay_interj_gap_sec=float(ns.overlay_interj_gap_sec),
        overlay_mode=str(ns.overlay_mode),
        translate_bearer=translate_bearer
        if translate_bearer is not None
        else (os.environ.get("OPENAI_API_KEY") or None),
        system_prompt=system_prompt,
        glossary=glossary,
    )
