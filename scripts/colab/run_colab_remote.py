#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tarfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import aiohttp
from aiohttp import WSMsgType, web


ROOT = Path.cwd()
DEFAULT_TOKEN = os.environ.get("CRISPASR_REMOTE_KEY") or secrets.token_urlsafe(32)
LLAMA_PORT = 8081
PROXY_PORT = 7860


def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=str(cwd) if cwd else None)


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        print(f"[skip] {target}", flush=True)
        return
    print(f"[download] {url}", flush=True)
    urllib.request.urlretrieve(url, target)


def ensure_models() -> None:
    files = [
        (
            "https://huggingface.co/CKHO/cohere-asr-ja-GGUF/resolve/main/cohere-asr-ja-q6_k.gguf",
            ROOT / "models" / "asr" / "cohere-asr-ja-q6_k.gguf",
        ),
        (
            "https://huggingface.co/cstr/firered-vad-GGUF/resolve/aa92f55584d0fa37b9aae9a9c10bee275a0af240/firered-vad.gguf",
            ROOT / "models" / "vad" / "firered-vad.gguf",
        ),
        (
            "https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF/resolve/2a9c104757ab36f679ae8e6006b437cf9867c329/Hy-MT2-1.8B-Q4_K_M.gguf",
            ROOT / "models" / "translation" / "Hy-MT2-1.8B-Q4_K_M.gguf",
        ),
    ]
    for url, target in files:
        download(url, target)


def ensure_cloudflared() -> Path:
    path = ROOT / "tools" / "cloudflared"
    if path.exists():
        return path
    download(
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
        path,
    )
    path.chmod(0o755)
    return path


def extract_archive(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(dest)
        return
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            tf.extractall(dest)
        return
    raise SystemExit(f"Unsupported archive format: {archive}")


def find_executable(root: Path, name: str) -> Path | None:
    for path in root.rglob(name):
        if path.is_file():
            path.chmod(path.stat().st_mode | 0o755)
            return path
    return None


def crispasr_release_asset_urls() -> list[str]:
    url = os.environ.get("CRISPASR_URL", "").strip()
    if not url:
        with urllib.request.urlopen("https://api.github.com/repos/CrispStrobe/CrispASR/releases/latest", timeout=20) as resp:
            release = json.loads(resp.read().decode("utf-8"))
        candidates: list[tuple[int, str]] = []
        for asset in release.get("assets", []):
            name = str(asset.get("name") or "").lower()
            if name.startswith(("libcrispasr", "crispasr-python")):
                continue
            if "linux" not in name or "x86_64" not in name:
                continue
            if "cuda" not in name and "vulkan" not in name:
                continue
            asset_url = str(asset.get("browser_download_url") or "")
            if not asset_url:
                continue
            score = 20 if "cuda" in name else 10
            candidates.append((score, asset_url))
        return [asset_url for _, asset_url in sorted(candidates, reverse=True)]
    return [url]


def download_crispasr_archive(url: str) -> Path:
    if not url:
        raise SystemExit("Could not find a Linux CrispASR release asset. Set CRISPASR_URL to a release archive URL.")
    archive = ROOT / "tools" / "cache" / Path(urllib.parse.urlparse(url).path).name
    download(url, archive)
    dest = ROOT / "tools" / "crispasr" / archive.name.removesuffix(".tar.gz").removesuffix(".tgz").removesuffix(".zip")
    if dest.exists():
        shutil.rmtree(dest)
    extract_archive(archive, dest)
    exe = find_executable(dest, "crispasr")
    if not exe:
        raise SystemExit(f"crispasr executable was not found after extracting {archive}")
    return exe


def build_crispasr() -> Path:
    crisp_dir = ROOT / "tools" / "CrispASR"
    exe = crisp_dir / "build" / "bin" / "crispasr"
    if exe.exists():
        return exe
    if not crisp_dir.exists():
        run(["git", "clone", "--depth", "1", "https://github.com/CrispStrobe/CrispASR", str(crisp_dir)])
    run(["cmake", "-B", "build", "-DCMAKE_BUILD_TYPE=Release", "-DGGML_CUDA=ON"], cwd=crisp_dir)
    run(["cmake", "--build", "build", "--config", "Release", "-j", "2"], cwd=crisp_dir)
    if not exe.exists():
        raise SystemExit(f"CrispASR build completed but executable was not found: {exe}")
    return exe


def check_crispasr_binary(exe: Path) -> bool:
    try:
        proc = subprocess.run(
            [str(exe), "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=False,
        )
    except Exception as exc:
        print(f"[warn] CrispASR binary check failed: {exc}", flush=True)
        return False
    if proc.returncode == 0:
        return True
    detail = (proc.stderr or proc.stdout or "").strip()
    print(f"[warn] CrispASR binary is not runnable: {detail}", flush=True)
    return False


def github_release_asset_urls(repo: str, tag: str | None, predicate) -> list[str]:
    api_url = f"https://api.github.com/repos/{repo}/releases/{'tags/' + tag if tag else 'latest'}"
    with urllib.request.urlopen(api_url, timeout=20) as resp:
        release = json.loads(resp.read().decode("utf-8"))
    candidates: list[tuple[int, str]] = []
    for asset in release.get("assets", []):
        name = str(asset.get("name") or "").lower()
        asset_url = str(asset.get("browser_download_url") or "")
        score = predicate(name, asset_url)
        if score:
            candidates.append((score, asset_url))
    return [asset_url for _, asset_url in sorted(candidates, reverse=True)]


def official_llama_asset_urls(backend: str) -> list[str]:
    def score(name: str, asset_url: str) -> int:
        if not asset_url or not name.endswith((".zip", ".tar.gz", ".tgz")):
            return 0
        if any(token in name for token in ("win", "windows", "macos", "darwin", "osx", "android")):
            return 0
        if "linux" not in name and "ubuntu" not in name:
            return 0
        if "x64" not in name and "x86_64" not in name:
            return 0
        is_vulkan = "vulkan" in name
        is_rocm = "rocm" in name
        is_openvino = "openvino" in name
        is_cpu = not (is_vulkan or is_rocm or is_openvino or "cuda" in name or "cu" in name)
        if backend == "vulkan" and not is_vulkan:
            return 0
        if backend == "official-cpu" and not is_cpu:
            return 0
        score_value = 0
        if is_vulkan:
            score_value += 30
        if is_rocm:
            score_value += 20
        if is_cpu:
            score_value += 5
        if "ubuntu" in name:
            score_value += 10
        if "server" in name:
            score_value += 2
        return score_value

    return github_release_asset_urls("ggml-org/llama.cpp", None, score)


def ai_dock_llama_asset_urls() -> list[str]:
    tag = os.environ.get("AI_DOCK_LLAMA_TAG", "").strip() or None

    def score(name: str, asset_url: str) -> int:
        if not asset_url or not name.endswith((".tar.gz", ".tgz")):
            return 0
        if "cuda" not in name or "amd64" not in name:
            return 0
        score_value = 50
        if "12.8" in name:
            score_value += 10
        return score_value

    return github_release_asset_urls("ai-dock/llama.cpp-cuda", tag, score)


def download_llama_cpp_archive(url: str) -> Path:
    archive = ROOT / "tools" / "cache" / Path(urllib.parse.urlparse(url).path).name
    download(url, archive)
    dest = ROOT / "tools" / "llama.cpp"
    if dest.exists():
        shutil.rmtree(dest)
    extract_archive(archive, dest)
    server = find_executable(dest, "llama-server")
    if not server:
        raise SystemExit(f"llama-server executable was not found after extracting {archive}")
    return server


def download_llama_cpp_from_github(backend: str) -> Path:
    url = os.environ.get("LLAMA_CPP_URL", "").strip()
    urls: list[str]
    if url:
        urls = [url]
    elif backend == "ai-dock-cuda":
        urls = ai_dock_llama_asset_urls()
    elif backend in {"vulkan", "official-cpu"}:
        urls = official_llama_asset_urls(backend)
    else:
        urls = ai_dock_llama_asset_urls() + official_llama_asset_urls("vulkan") + official_llama_asset_urls("official-cpu")
    if not urls:
        raise SystemExit(
            f"Could not find a Linux llama.cpp release asset for backend={backend}. "
            "Set LLAMA_CPP_URL, set LLAMA_SERVER, choose another LLAMA_BACKEND, or rerun with --build-llama."
        )
    last_error = ""
    for candidate in urls:
        try:
            return download_llama_cpp_archive(candidate)
        except SystemExit as exc:
            last_error = str(exc)
            print(f"[warn] llama.cpp candidate failed: {last_error}", flush=True)
    raise SystemExit(last_error or f"No usable llama.cpp asset for backend={backend}")


def build_llama_cpp() -> Path:
    llama_dir = ROOT / "tools" / "llama.cpp"
    server = llama_dir / "build" / "bin" / "llama-server"
    if server.exists():
        return server
    if not llama_dir.exists():
        run(["git", "clone", "--depth", "1", "https://github.com/ggml-org/llama.cpp", str(llama_dir)])
    run(["cmake", "-B", "build", "-DGGML_CUDA=ON", "-DLLAMA_CURL=OFF"], cwd=llama_dir)
    run(["cmake", "--build", "build", "--config", "Release", "-j", "2"], cwd=llama_dir)
    return server


def find_llama_server(*, backend: str, allow_build: bool) -> Path:
    override = os.environ.get("LLAMA_SERVER")
    if override and Path(override).exists():
        return Path(override)
    found = shutil.which("llama-server")
    if found:
        return Path(found)
    if backend == "build-cuda":
        return build_llama_cpp()
    try:
        return download_llama_cpp_from_github(backend)
    except SystemExit:
        if not allow_build:
            raise
        print("[warn] llama.cpp prebuilt download failed; falling back to source build.", flush=True)
        return build_llama_cpp()


def find_crispasr() -> Path:
    override = os.environ.get("CRISPASR_EXE")
    if override and Path(override).exists():
        exe = Path(override)
        if not check_crispasr_binary(exe):
            raise SystemExit(f"CRISPASR_EXE is set but not runnable: {exe}")
        return exe
    found = shutil.which("crispasr")
    if found:
        exe = Path(found)
        if check_crispasr_binary(exe):
            return exe
    for url in crispasr_release_asset_urls():
        try:
            exe = download_crispasr_archive(url)
        except SystemExit as exc:
            print(f"[warn] CrispASR download candidate failed: {exc}", flush=True)
            continue
        if check_crispasr_binary(exe):
            return exe
    print("[warn] Downloaded CrispASR assets are incompatible with this Colab runtime; building CrispASR from source.", flush=True)
    exe = build_crispasr()
    if not check_crispasr_binary(exe):
        raise SystemExit(f"Built CrispASR is not runnable: {exe}")
    return exe


async def terminate_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    proc.send_signal(signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), timeout=2)
    except TimeoutError:
        proc.kill()
        await proc.wait()


def require_auth(req: web.Request, token: str) -> web.Response | None:
    header = req.headers.get("Authorization", "")
    if header != f"Bearer {token}":
        return web.json_response({"error": "unauthorized"}, status=401)
    return None


async def wait_health(url: str, timeout_sec: float = 180) -> bool:
    deadline = time.monotonic() + timeout_sec
    async with aiohttp.ClientSession() as session:
        while time.monotonic() < deadline:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    if 200 <= resp.status < 300:
                        return True
            except Exception:
                pass
            await asyncio.sleep(2)
    return False


def make_app(token: str, crispasr: Path, llama_base: str) -> web.Application:
    app = web.Application()

    async def health(req: web.Request) -> web.Response:
        auth = require_auth(req, token)
        if auth is not None:
            return auth
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(f"{llama_base}/health", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                    llama_online = 200 <= resp.status < 300
            except Exception:
                llama_online = False
        return web.json_response({"asr": "ready", "llama": "online" if llama_online else "offline"})

    async def proxy_chat(req: web.Request) -> web.StreamResponse:
        auth = require_auth(req, token)
        if auth is not None:
            return auth
        body = await req.read()
        headers = {"Content-Type": req.headers.get("Content-Type", "application/json")}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{llama_base}/v1/chat/completions",
                data=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                out = await resp.read()
                return web.Response(status=resp.status, body=out, content_type=resp.content_type)

    async def asr_stream(req: web.Request) -> web.WebSocketResponse:
        auth = require_auth(req, token)
        if auth is not None:
            raise web.HTTPUnauthorized(text='{"error":"unauthorized"}', content_type="application/json")
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=4 * 1024 * 1024)
        await ws.prepare(req)

        first = await ws.receive(timeout=10)
        if first.type != WSMsgType.TEXT:
            await ws.close(code=1002, message=b"expected config")
            return ws
        try:
            config = json.loads(first.data)
            crisp_args = [str(x) for x in config.get("crisp_args", [])]
        except Exception:
            await ws.close(code=1002, message=b"invalid config")
            return ws
        if not crisp_args:
            await ws.close(code=1002, message=b"missing crisp_args")
            return ws

        cmd = [str(crispasr), "--stream", "--monitor", "--no-prints", *crisp_args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ROOT),
        )

        async def stdout_to_ws() -> None:
            assert proc.stdout
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await ws.send_str(line.decode("utf-8", errors="replace").strip())

        async def stderr_log() -> None:
            assert proc.stderr
            while True:
                line = await proc.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    print(f"[crispasr] {text}", flush=True)

        tasks = [asyncio.create_task(stdout_to_ws()), asyncio.create_task(stderr_log())]
        try:
            async for msg in ws:
                if proc.returncode is not None:
                    await ws.close(code=1011, message=b"crispasr exited")
                    break
                if msg.type == WSMsgType.BINARY and proc.stdin:
                    try:
                        proc.stdin.write(msg.data)
                        await proc.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        await ws.close(code=1011, message=b"crispasr stdin closed")
                        break
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await terminate_process(proc)
        return ws

    app.router.add_get("/health", health)
    app.router.add_post("/v1/chat/completions", proxy_chat)
    app.router.add_get("/asr/stream", asr_stream)
    return app


def _print_value_box(title: str, value: str) -> None:
    """Print one value so it is clearly visible in a Colab/Kaggle console.

    ``run_colab_remote.py`` runs as a ``!python`` subprocess, where
    ``IPython.display.display()`` only prints ``<IPython.core.display.HTML
    object>`` and does not render. So instead of relying on a notebook display
    hook or a clipboard button, we print an obvious box with separation lines
    that is guaranteed to be visible and easy to copy.
    """
    bar = "=" * 60
    print("", flush=True)
    print(bar, flush=True)
    print(f"  {title}", flush=True)
    print(bar, flush=True)
    print(f"  {value}", flush=True)
    print(bar, flush=True)
    print("  請全選這一行 → Ctrl+C 複製", flush=True)
    print("", flush=True)


def display_copy_box(title: str, value: str) -> None:
    """Show a token/URL value prominently via print()."""
    _print_value_box(title, value)


def display_connection_block(token: str, url: str) -> None:
    """Print the token and URL as two clearly separated steps.

    On Windows ``colab-token.bat`` asks for the values in two prompts (Step 1 =
    token, Step 2 = URL), so this prints them with matching step labels to make
    it obvious which value goes where.
    """
    bar = "=" * 60
    print("", flush=True)
    print(bar, flush=True)
    print("  在 Windows 執行 colab-token.bat，然後分別複製下面兩個值貼上", flush=True)
    print(bar, flush=True)
    print("  Step 1 - TOKEN（貼到 colab-token.bat 的 Step 1 提示）", flush=True)
    print(f"  CRISPASR_REMOTE_KEY={token}", flush=True)
    print(bar, flush=True)
    print("  Step 2 - URL（貼到 colab-token.bat 的 Step 2 提示）", flush=True)
    print(f"  TUNNEL={url}", flush=True)
    print(bar, flush=True)
    print("  請全選每一行 → Ctrl+C 複製", flush=True)
    print("", flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Colab remote CrispASR + llama.cpp proxy for crisp-caption.")
    parser.add_argument("--token", default=DEFAULT_TOKEN)
    parser.add_argument("--skip-models", action="store_true")
    parser.add_argument(
        "--llama-backend",
        default=os.environ.get("LLAMA_BACKEND", "auto"),
        choices=("auto", "ai-dock-cuda", "vulkan", "official-cpu", "build-cuda"),
        help="llama.cpp runtime source: auto, third-party CUDA, official Vulkan, official CPU, or local CUDA build.",
    )
    parser.add_argument("--build-llama", action="store_true", help="Allow fallback source build if no prebuilt llama.cpp asset is found.")
    parser.add_argument("--llama-server", default=os.environ.get("LLAMA_SERVER", ""))
    parser.add_argument("--crispasr", default=os.environ.get("CRISPASR_EXE", ""))
    ns = parser.parse_args()

    run([sys.executable, "-m", "pip", "install", "-q", "aiohttp"])
    if not ns.skip_models:
        ensure_models()
    cloudflared = ensure_cloudflared()

    llama_server = Path(ns.llama_server) if ns.llama_server else None
    if not llama_server:
        llama_server = find_llama_server(backend=ns.llama_backend, allow_build=ns.build_llama)

    crispasr = Path(ns.crispasr) if ns.crispasr else find_crispasr()

    llama_model = ROOT / "models" / "translation" / "Hy-MT2-1.8B-Q4_K_M.gguf"
    llama_cmd = [
        str(llama_server),
        "-m",
        str(llama_model),
        "-a",
        "Hy-MT2-1.8B",
        "-ngl",
        "all",
        "-c",
        "8192",
        "-b",
        "2048",
        "-ub",
        "1024",
        "-np",
        "1",
        "--host",
        "127.0.0.1",
        "--port",
        str(LLAMA_PORT),
    ]
    print("+ " + " ".join(llama_cmd), flush=True)
    llama_env = os.environ.copy()
    llama_lib_dir = str(Path(llama_server).resolve().parent)
    existing_ld_path = llama_env.get("LD_LIBRARY_PATH", "")
    llama_env["LD_LIBRARY_PATH"] = llama_lib_dir if not existing_ld_path else f"{llama_lib_dir}:{existing_ld_path}"
    llama_proc = subprocess.Popen(llama_cmd, env=llama_env)
    if not await wait_health(f"http://127.0.0.1:{LLAMA_PORT}/health"):
        raise SystemExit("llama-server did not become healthy")

    app = make_app(ns.token, crispasr, f"http://127.0.0.1:{LLAMA_PORT}")
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", PROXY_PORT).start()

    tunnel_cmd = [str(cloudflared), "tunnel", "--url", f"http://127.0.0.1:{PROXY_PORT}", "--no-autoupdate"]
    print("+ " + " ".join(tunnel_cmd), flush=True)
    tunnel = await asyncio.create_subprocess_exec(
        *tunnel_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    print(f"CRISPASR_REMOTE_KEY={ns.token}", flush=True)
    print("Copy the trycloudflare.com URL printed below into the local profile:", flush=True)
    print("  remote_asr_url = wss://<host>/asr/stream", flush=True)
    print("  translate_url = https://<host>/v1/chat/completions", flush=True)
    display_copy_box("CRISPASR_REMOTE_KEY", ns.token)
    shown_url = False
    try:
        assert tunnel.stdout
        while True:
            line = await tunnel.stdout.readline()
            if line:
                text = line.decode("utf-8", errors="replace").rstrip()
                print(text, flush=True)
                if not shown_url and "trycloudflare.com" in text:
                    shown_url = True
                    display_copy_box("Cloudflare 地址", text)
                    display_connection_block(ns.token, text)
            elif tunnel.returncode is not None:
                raise SystemExit(tunnel.returncode)
            else:
                await asyncio.sleep(0.2)
    finally:
        tunnel.terminate()
        await tunnel.wait()
        llama_proc.terminate()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
