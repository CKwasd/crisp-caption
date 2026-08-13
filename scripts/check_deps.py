from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles" / "profile-stable-ja.jsonc"


def _strip_jsonc(text: str) -> str:
    """Remove JSONC ``//`` and ``/* */`` comments without touching strings.

    Kept inline here (rather than importing bridge_config) so this standalone
    check script has no import-path dependency. See bridge_config.strip_jsonc.
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
        if ch == '"' or ch == "'":
            in_string = True
            string_quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and nxt == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


FAILED = 0


def ok(message: str) -> None:
    print(f"[OK] {message}")


def warn(message: str, fix: str = "") -> None:
    print(f"[WARN] {message}")
    if fix:
        print(f"       Fix: {fix}")


def fail(message: str, fix: str = "") -> None:
    global FAILED
    FAILED += 1
    print(f"[FAIL] {message}")
    if fix:
        print(f"       Fix: {fix}")


def import_exists(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def load_profile() -> dict[str, Any] | None:
    if not PROFILE.is_file():
        fail("profiles/profile-stable-ja.jsonc not found", "crisp-caption.bat (menu 1) setup")
        return None
    try:
        data = json.loads(_strip_jsonc(PROFILE.read_text(encoding="utf-8")))
    except Exception as exc:
        fail(f"profiles/profile-stable-ja.jsonc is invalid JSON: {exc}")
        return None
    ok("profiles/profile-stable-ja.jsonc exists")
    return data if isinstance(data, dict) else None


def resolve_profile_path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = PROFILE.parent / path
    return path.resolve()


def crisp_arg_path(profile: dict[str, Any], flag: str) -> Path | None:
    args = profile.get("crisp_args")
    if not isinstance(args, list):
        fail("profile crisp_args must be a list")
        return None
    for idx, token in enumerate(args[:-1]):
        if token == flag:
            return resolve_profile_path(str(args[idx + 1]))
    return None


def check_python() -> None:
    ok(f"Python {sys.version.split()[0]}: {sys.executable}")
    if sys.version_info < (3, 11):
        fail("Python 3.11+ is required")


def check_packages() -> None:
    for package in ("aiohttp", "aiortc", "av", "numpy"):
        if import_exists(package):
            ok(f"Python package import works: {package}")
        else:
            fail(f"Missing Python package: {package}", "crisp-caption.bat (menu 1) setup")
    if import_exists("PySide6"):
        ok("Optional overlay package import works: PySide6")
    else:
        warn("Optional overlay package missing: PySide6", "crisp-caption.bat (menu 1) setup")


def check_frontend() -> None:
    static = ROOT / "static"
    missing = [name for name in ("index.html", "app.css", "app.js") if not (static / name).is_file()]
    if missing:
        fail(f"static UI missing: {', '.join(missing)}")
    else:
        ok("static/index.html + app.css + app.js exist")


def check_executable(path: Path, label: str, fix: str) -> None:
    if path.is_file():
        ok(f"{label} found: {path}")
    else:
        fail(f"{label} not found: {path}", fix)


def is_local_url(url: str) -> bool:
    try:
        host = urllib.parse.urlsplit(url).hostname or ""
    except ValueError:
        return False
    return host in {"127.0.0.1", "localhost", "::1"}


def asr_health_url(remote_asr_url: str) -> str:
    parts = urllib.parse.urlsplit(remote_asr_url)
    scheme = "https" if parts.scheme == "wss" else parts.scheme or "https"
    return urllib.parse.urlunsplit((scheme, parts.netloc, "/health", "", ""))


def check_profile(profile: dict[str, Any]) -> None:
    asr_mode = str(profile.get("asr_mode") or "local").strip().lower()
    if asr_mode not in {"local", "remote"}:
        fail(f"Unsupported asr_mode: {asr_mode}", 'Use "local" or "remote"')
        asr_mode = "local"

    if asr_mode == "remote":
        remote_asr_url = str(profile.get("remote_asr_url") or "").strip()
        bearer_env = str(profile.get("remote_asr_bearer_env") or "CRISPASR_REMOTE_KEY").strip()
        bearer = os.environ.get(bearer_env) if bearer_env else None
        if remote_asr_url.startswith(("wss://", "ws://")):
            ok(f"Remote ASR URL configured: {remote_asr_url}")
            check_remote_health(remote_asr_url, bearer)
        else:
            fail("remote_asr_url must be a ws:// or wss:// URL", "Paste the Colab Cloudflare Tunnel /asr/stream URL into the profile")
        if bearer:
            ok(f"Remote ASR token env is set: {bearer_env}")
        else:
            fail(f"Remote ASR token env is not set: {bearer_env}", f"Run: set {bearer_env}=<Colab token>")
    else:
        crisp = str(profile.get("crispasr") or "").strip()
        if crisp.lower() == "auto":
            crisp_path = ROOT / "tools" / "crispasr" / "crispasr.exe"
        elif crisp and ("/" in crisp or "\\" in crisp or crisp.endswith(".exe")):
            crisp_path = Path(crisp)
            if not crisp_path.is_absolute():
                crisp_path = ROOT / crisp_path
        elif crisp:
            found = shutil.which(crisp)
            if found:
                ok(f"CrispASR found on PATH: {found}")
                crisp_path = None
            else:
                fail(f"CrispASR executable not found on PATH: {crisp}", "crisp-caption.bat (menu 2) download CrispASR or edit profiles\\profile-stable-ja.jsonc")
                crisp_path = None
        else:
            fail("profile crispasr is empty", "Set crispasr to tools/crispasr/crispasr.exe")
            crisp_path = None
        if crisp_path is not None:
            check_executable(crisp_path, "CrispASR", "crisp-caption.bat (menu 2) download CrispASR")

        asr_model = crisp_arg_path(profile, "-m")
        if asr_model:
            check_executable(asr_model, "ASR model", "crisp-caption.bat (menu 2) download models")
        vad_model = crisp_arg_path(profile, "-vm")
        if vad_model:
            check_executable(vad_model, "VAD model", "crisp-caption.bat (menu 2) download models")

    translate_model = str(profile.get("translate_model") or "").strip()
    if translate_model:
        translate_url = str(profile.get("translate_url") or "http://127.0.0.1:8080/v1/chat/completions")
        if is_local_url(translate_url):
            check_executable(ROOT / "tools" / "llama.cpp" / "llama-server.exe", "llama-server", "crisp-caption.bat (menu 2) download llama.cpp")
            check_executable(ROOT / "models" / "translation" / "Hy-MT2-1.8B-Q4_K_M.gguf", "Translation model", "crisp-caption.bat (menu 2) download models")
        else:
            ok(f"Remote translation URL configured: {translate_url}")
        check_translation_health(translate_url)
    else:
        warn("Translation is disabled in profile", 'Set "translate_model": "Hy-MT2-1.8B" in profiles\\profile-stable-ja.jsonc')


def check_port(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            warn(f"Port {port} is already in use")
        else:
            ok(f"Port {port} is free")


def check_remote_health(remote_asr_url: str, bearer: str | None) -> None:
    health = asr_health_url(remote_asr_url)
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    req = urllib.request.Request(health, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if 200 <= resp.status < 300:
                ok(f"Remote ASR service is reachable: {health}")
            else:
                warn(f"Remote ASR service returned HTTP {resp.status}: {health}")
    except urllib.error.HTTPError as exc:
        warn(f"Remote ASR health returned HTTP {exc.code}: {health}", "Check the Colab token and tunnel URL")
    except (urllib.error.URLError, TimeoutError) as exc:
        warn(f"Remote ASR service is not reachable yet: {exc}", "Start the Colab service and refresh the Cloudflare Tunnel URL")


def check_translation_health(translate_url: str) -> None:
    health = "http://127.0.0.1:8080/health"
    if "/v1/" in translate_url:
        health = translate_url.split("/v1/", 1)[0] + "/health"
    headers = {}
    bearer = os.environ.get("OPENAI_API_KEY")
    if bearer and not is_local_url(translate_url):
        headers["Authorization"] = f"Bearer {bearer}"
    req = urllib.request.Request(health, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5 if not is_local_url(translate_url) else 2) as resp:
            if 200 <= resp.status < 300:
                ok(f"Translation server is reachable: {health}")
            else:
                warn(f"Translation server returned HTTP {resp.status}: {health}")
    except urllib.error.HTTPError as exc:
        warn(f"Translation server returned HTTP {exc.code}: {health}", "Check OPENAI_API_KEY/token and the tunnel URL")
    except (urllib.error.URLError, TimeoutError) as exc:
        fix = "Start the Colab service and refresh the Cloudflare Tunnel URL" if not is_local_url(translate_url) else "run-windows.bat will start it, or run scripts\\start-translation-server-windows.bat"
        warn(f"Translation server is not running yet: {exc}", fix)


def main() -> int:
    print("=== crisp-caption dependency check ===")
    check_python()
    check_packages()
    check_frontend()
    check_port(8765)
    profile = load_profile()
    if profile is not None:
        check_profile(profile)
    print()
    if FAILED:
        print(f"[FAIL] {FAILED} required check(s) failed.")
        return 1
    print("[OK] Required checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
