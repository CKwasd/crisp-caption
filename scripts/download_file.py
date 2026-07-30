from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "crisp-caption-download/1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_under_root(raw: str) -> Path:
    target = (ROOT / raw).resolve()
    if ROOT.resolve() != target and ROOT.resolve() not in target.parents:
        raise SystemExit(f"Refusing to write outside project root: {raw}")
    return target


def http_get_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"GitHub API failed HTTP {exc.code}: {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"GitHub API unreachable: {exc}") from exc


def download(url: str, target: Path, expected_sha256: str = "", *, force: bool = False) -> None:
    if not url or "TODO" in url:
        raise SystemExit("Download URL is not configured yet. Edit the manifest or BAT file first.")
    if not url.startswith("https://"):
        raise SystemExit(f"Refusing non-HTTPS URL: {url}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not force:
        if expected_sha256:
            actual = sha256_file(target)
            if actual.lower() == expected_sha256.lower():
                print(f"[OK] {target} already exists")
                return
            print(f"[WARN] Existing file hash mismatch, replacing: {target}")
        else:
            print(f"[OK] {target} already exists")
            return

    with tempfile.NamedTemporaryFile(delete=False, suffix=target.suffix or ".download") as tmp:
        temp_path = Path(tmp.name)
    try:
        print(f"[GET] {url}")
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=600) as resp, temp_path.open("wb") as out:
            shutil.copyfileobj(resp, out)
        if expected_sha256:
            actual = sha256_file(temp_path)
            if actual.lower() != expected_sha256.lower():
                raise SystemExit(f"sha256 mismatch for {target}\nexpected {expected_sha256}\nactual   {actual}")
        elif not force:
            print(f"[WARN] No sha256 configured for {target.name}; downloaded without hash verification.")
        shutil.move(str(temp_path), target)
        print(f"[OK] Wrote {target}")
    finally:
        temp_path.unlink(missing_ok=True)


def extract_zip(archive: Path, dest: Path, strip_top_level: bool, *, merge: bool = False) -> None:
    if not archive.is_file():
        raise SystemExit(f"Archive not found: {archive}")
    if dest.exists() and not merge:
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        top_parts = {Path(member.filename).parts[0] for member in members if Path(member.filename).parts}
        strip_prefix = next(iter(top_parts)) if strip_top_level and len(top_parts) == 1 else ""
        for member in members:
            parts = Path(member.filename).parts
            if not parts:
                continue
            relative = Path(*parts[1:]) if strip_prefix and parts[0] == strip_prefix else Path(*parts)
            if not str(relative):
                continue
            target = (dest / relative).resolve()
            if dest.resolve() != target and dest.resolve() not in target.parents:
                raise SystemExit(f"Refusing unsafe zip member: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)


def detect_cuda() -> bool:
    """True when an NVIDIA GPU / CUDA user-mode driver looks available on this machine."""
    nvsmi = shutil.which("nvidia-smi")
    if nvsmi:
        try:
            proc = subprocess.run(
                [nvsmi, "-L"],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if proc.returncode == 0 and "GPU" in (proc.stdout or ""):
                return True
        except (OSError, subprocess.SubprocessError):
            pass
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    if (system_root / "System32" / "nvcuda.dll").is_file():
        return True
    return False


def resolve_gpu_backend(requested: str = "auto") -> str:
    req = (requested or "auto").strip().lower()
    if req in {"cuda", "vulkan"}:
        return req
    if req != "auto":
        raise SystemExit(f"Unknown backend {requested!r}; use auto, cuda, or vulkan")
    if detect_cuda():
        print("[INFO] CUDA detected (nvidia-smi / nvcuda.dll) — preferring CUDA builds")
        return "cuda"
    print("[INFO] CUDA not detected — using Vulkan builds")
    return "vulkan"


def load_manifest(path: Path) -> list[dict[str, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, list):
        raise SystemExit(f"Manifest must contain an artifacts list: {path}")
    return artifacts


def parse_csv(raw: str) -> list[str]:
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def _score_asset(name: str, include: list[str], exclude: list[str]) -> int:
    lower = name.lower()
    if not lower.endswith((".zip", ".tar.gz", ".tgz", ".7z")):
        return 0
    if any(token in lower for token in exclude):
        return 0
    if any(token not in lower for token in include):
        return 0
    score = 100 - min(len(name), 80)
    if "vulkan" in lower:
        score += 20
    if "cuda" in lower and "cudart" not in lower:
        score += 25
    if lower.startswith("llama-") and "bin-win" in lower:
        score += 30
    if "cudart" in lower:
        score -= 50
    if "x64" in lower or "x86_64" in lower:
        score += 10
    # Prefer broader CUDA 12.x over bleeding 13.x when both match.
    if "cuda-12" in lower or "cu12" in lower:
        score += 5
    return score


def pick_github_asset(
    repo: str,
    *,
    include: list[str],
    exclude: list[str],
    tag: str = "",
) -> tuple[str, str, str]:
    """Return (tag_name, asset_name, browser_download_url) for the best matching asset.

    When ``tag`` is empty, walk recent releases (not only GitHub's ``latest``, which may
    be an unrelated platform-only release).
    """
    if tag:
        releases = [http_get_json(f"https://api.github.com/repos/{repo}/releases/tags/{tag}")]
    else:
        releases = http_get_json(f"https://api.github.com/repos/{repo}/releases?per_page=30")
        if not isinstance(releases, list):
            raise SystemExit(f"Unexpected GitHub releases payload for {repo}")

    best: tuple[int, str, str, str] | None = None  # score, tag, name, url
    for release in releases:
        if not isinstance(release, dict):
            continue
        tag_name = str(release.get("tag_name") or "unknown")
        for asset in release.get("assets") or []:
            name = str(asset.get("name") or "")
            url = str(asset.get("browser_download_url") or "")
            if not name or not url:
                continue
            score = _score_asset(name, include, exclude)
            if score <= 0:
                continue
            candidate = (score, tag_name, name, url)
            if best is None or candidate[0] > best[0]:
                best = candidate
        # Prefer the newest release that has any match (list is newest-first).
        if best is not None and not tag:
            break

    if best is None:
        need = ", ".join(include) if include else "(any)"
        raise SystemExit(
            f"No release asset matched repo={repo} include=[{need}] exclude={exclude}"
            + (f" tag={tag}" if tag else " (searched recent releases)")
        )
    return best[1], best[2], best[3]


def _ensure_exe(dest: Path, exe_name: str) -> Path:
    exe = dest / exe_name
    if exe.is_file():
        return exe
    found = next((p for p in dest.rglob(exe_name) if p.is_file()), None)
    if found and found != exe:
        exe.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(found), exe)
    if not exe.is_file():
        raise SystemExit(f"{exe_name} not found after extract under {dest}")
    return exe


def install_github(
    *,
    repo: str,
    include: list[str],
    exclude: list[str],
    dest: Path,
    exe_name: str,
    strip_top_level: bool,
    tag: str = "",
    force: bool = False,
    backend: str = "",
    extra_stamp: str = "",
) -> tuple[str, str]:
    tag_name, asset_name, url = pick_github_asset(repo, include=include, exclude=exclude, tag=tag)
    stamp = dest / ".release-id"
    backend_file = dest / ".backend"
    stamp_value = f"{tag_name}\n{asset_name}\n{url}\n{extra_stamp}"
    exe = dest / exe_name
    if (
        not force
        and exe.is_file()
        and stamp.is_file()
        and stamp.read_text(encoding="utf-8") == stamp_value
    ):
        print(f"[OK] {dest} already at {tag_name} ({asset_name})")
        if backend:
            backend_file.write_text(backend + "\n", encoding="utf-8")
        return tag_name, asset_name

    cache = ROOT / "tools" / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^\w.\-]+", "_", asset_name)
    archive = cache / f"{repo.replace('/', '_')}-{tag_name}-{safe_name}"
    need_force = force or (stamp.is_file() and stamp.read_text(encoding="utf-8") != stamp_value)
    download(url, archive, force=need_force)
    print(f"[EXTRACT] {archive.name} -> {dest}  (release {tag_name})")
    extract_zip(archive, dest, strip_top_level=strip_top_level)
    _ensure_exe(dest, exe_name)
    stamp.write_text(stamp_value, encoding="utf-8")
    if backend:
        backend_file.write_text(backend + "\n", encoding="utf-8")
    print(f"[OK] Installed {dest / exe_name} from {tag_name} / {asset_name}")
    return tag_name, asset_name


def _cuda_version_from_name(name: str) -> str:
    match = re.search(r"cuda[-_]?(\d+\.\d+)", name.lower())
    return match.group(1) if match else ""


def install_crispasr_windows(*, backend: str = "auto", force: bool = False, tag: str = "") -> None:
    gpu = resolve_gpu_backend(backend)
    dest = resolve_under_root("tools/crispasr")
    if gpu == "cuda":
        try:
            install_github(
                repo="CrispStrobe/CrispASR",
                include=["windows", "cuda"],
                exclude=["libcrispasr", "python", ".tar"],
                dest=dest,
                exe_name="crispasr.exe",
                strip_top_level=True,
                tag=tag,
                force=force,
                backend="cuda",
            )
            return
        except SystemExit as exc:
            print(f"[WARN] CUDA CrispASR asset unavailable ({exc}); falling back to Vulkan")
            gpu = "vulkan"
    install_github(
        repo="CrispStrobe/CrispASR",
        include=["windows", "vulkan"],
        exclude=["libcrispasr", "python", ".tar"],
        dest=dest,
        exe_name="crispasr.exe",
        strip_top_level=True,
        tag=tag,
        force=force,
        backend="vulkan",
    )


def install_llama_windows(*, backend: str = "auto", force: bool = False, tag: str = "") -> None:
    gpu = resolve_gpu_backend(backend)
    dest = resolve_under_root("tools/llama.cpp")
    if gpu == "cuda":
        try:
            tag_name, asset_name = install_github(
                repo="ggml-org/llama.cpp",
                include=["win", "cuda"],
                exclude=["cudart", "vulkan", "rocm", "kompute", "sycl", "opencl", "openvino"],
                dest=dest,
                exe_name="llama-server.exe",
                strip_top_level=True,
                tag=tag,
                force=force,
                backend="cuda",
            )
            cuda_ver = _cuda_version_from_name(asset_name)
            cudart_include = ["win", "cudart", "cuda"]
            if cuda_ver:
                cudart_include.append(cuda_ver)
            try:
                c_tag, c_name, c_url = pick_github_asset(
                    "ggml-org/llama.cpp",
                    include=cudart_include,
                    exclude=["vulkan"],
                    tag=tag_name if not tag else tag,
                )
                cache = ROOT / "tools" / "cache"
                safe = re.sub(r"[^\w.\-]+", "_", c_name)
                archive = cache / f"ggml-org_llama.cpp-{c_tag}-{safe}"
                download(c_url, archive, force=force)
                print(f"[EXTRACT] cudart {c_name} -> {dest}")
                extract_zip(archive, dest, strip_top_level=True, merge=True)
                # Refresh stamp so cudart is part of identity.
                stamp = dest / ".release-id"
                stamp.write_text(
                    f"{tag_name}\n{asset_name}\n+{c_name}\n",
                    encoding="utf-8",
                )
                (dest / ".backend").write_text("cuda\n", encoding="utf-8")
                print(f"[OK] Merged CUDA runtime {c_name}")
            except SystemExit as exc:
                print(f"[WARN] cudart package not merged: {exc}")
            return
        except SystemExit as exc:
            print(f"[WARN] CUDA llama.cpp asset unavailable ({exc}); falling back to Vulkan")
            gpu = "vulkan"
    install_github(
        repo="ggml-org/llama.cpp",
        include=["win", "vulkan"],
        exclude=["cuda", "cudart", "rocm", "kompute", "sycl", "opencl", "openvino"],
        dest=dest,
        exe_name="llama-server.exe",
        strip_top_level=True,
        tag=tag,
        force=force,
        backend="vulkan",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    one = sub.add_parser("one")
    one.add_argument("--url", required=True)
    one.add_argument("--target", required=True)
    one.add_argument("--sha256", default="")
    one.add_argument("--force", action="store_true")

    manifest = sub.add_parser("manifest")
    manifest.add_argument("--manifest", required=True)

    extract = sub.add_parser("extract")
    extract.add_argument("--archive", required=True)
    extract.add_argument("--dest", required=True)
    extract.add_argument("--strip-top-level", action="store_true")
    extract.add_argument("--delete-archive", action="store_true")

    gh = sub.add_parser("github-latest", help="Install latest (or tagged) GitHub release asset.")
    gh.add_argument("--repo", required=True, help="owner/name")
    gh.add_argument("--include", required=True, help="Comma-separated name substrings that must all match")
    gh.add_argument("--exclude", default="", help="Comma-separated name substrings to skip")
    gh.add_argument("--dest", required=True, help="Install directory under repo root")
    gh.add_argument("--exe", required=True, help="Expected executable name after extract")
    gh.add_argument("--strip-top-level", action="store_true")
    gh.add_argument("--tag", default="", help="Optional release tag; default = latest")
    gh.add_argument("--force", action="store_true", help="Re-download even if stamp matches")

    crisp = sub.add_parser("install-crispasr-windows", help="Install CrispASR (CUDA if available, else Vulkan).")
    crisp.add_argument("--backend", default="auto", choices=("auto", "cuda", "vulkan"))
    crisp.add_argument("--tag", default="")
    crisp.add_argument("--force", action="store_true")

    llama = sub.add_parser("install-llama-windows", help="Install llama.cpp (CUDA if available, else Vulkan).")
    llama.add_argument("--backend", default="auto", choices=("auto", "cuda", "vulkan"))
    llama.add_argument("--tag", default="")
    llama.add_argument("--force", action="store_true")

    detect = sub.add_parser("detect-cuda", help="Print cuda|none and exit 0/1.")

    args = parser.parse_args(argv)
    if args.cmd == "one":
        download(args.url, resolve_under_root(args.target), args.sha256, force=args.force)
    elif args.cmd == "manifest":
        manifest_path = resolve_under_root(args.manifest)
        for artifact in load_manifest(manifest_path):
            download(
                str(artifact.get("url") or ""),
                resolve_under_root(str(artifact.get("path") or "")),
                str(artifact.get("sha256") or ""),
            )
    elif args.cmd == "extract":
        archive = resolve_under_root(args.archive)
        extract_zip(archive, resolve_under_root(args.dest), args.strip_top_level)
        if args.delete_archive:
            archive.unlink(missing_ok=True)
    elif args.cmd == "github-latest":
        install_github(
            repo=args.repo.strip(),
            include=parse_csv(args.include),
            exclude=parse_csv(args.exclude),
            dest=resolve_under_root(args.dest),
            exe_name=args.exe,
            strip_top_level=args.strip_top_level,
            tag=args.tag.strip(),
            force=args.force,
        )
    elif args.cmd == "install-crispasr-windows":
        install_crispasr_windows(backend=args.backend, force=args.force, tag=args.tag.strip())
    elif args.cmd == "install-llama-windows":
        install_llama_windows(backend=args.backend, force=args.force, tag=args.tag.strip())
    elif args.cmd == "detect-cuda":
        ok = detect_cuda()
        print("cuda" if ok else "none")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
