# crisp-caption

**Real-time live Japanese captions and translation for browser video, livestreams, and OBS — running locally on your GPU.**

crisp-caption captures tab or microphone audio in the browser, streams it to CrispASR (a Vulkan-accelerated streaming ASR), translates finalized utterances with a local llama.cpp server, and displays subtitles in the browser, a transparent desktop overlay, or an OBS Browser Source.

The target setup is a Windows PC with a Vulkan-capable GPU and about 6 GB of VRAM. With the default Japanese ASR + Hy-MT2 translation profile, the intended live delay is roughly within 5 seconds on suitable hardware.

```text
browser tab/mic audio
  -> WebRTC
  -> Python bridge
  -> CrispASR Vulkan streaming ASR, local or remote Colab WebSocket
  -> llama.cpp translation server, local or remote Colab HTTP
  -> browser transcript / transparent overlay / OBS overlay
```

This repository does not vendor runtime binaries or model files. The setup scripts download GPU-accelerated builds (CUDA if available, else Vulkan) into `tools/` and model files into `models/`.

## Features

- **Real-time Japanese ASR** — stream browser tab or microphone audio to CrispASR for live speech recognition with partial (preview) and final results.
- **Japanese-to-English (and more) translation** — automatically translate finalized utterances with a local llama.cpp server (Hy-MT2 model).
- **Transparent desktop overlay** — a click-through, always-on-top subtitle window you can move, resize, and restyle with `Ctrl`.
- **OBS Browser Source overlay** — plug the subtitle stream straight into OBS as a transparent Browser Source for livestreaming.
- **Low-latency local inference** — Vulkan-accelerated ASR and LLM translation for ~5-second live delay on a consumer GPU.
- **Remote Colab / Kaggle compute** — offload ASR and translation to a free Colab or Kaggle notebook via Cloudflare Tunnel when you don't have a powerful GPU.
- **Single console entry point** — `crisp-caption.bat` handles setup, downloads, dependency checks, and startup.

## Use Cases

- **Live Japanese subtitle overlays for OBS** — add real-time Japanese captions to your livestream or VOD with a transparent OBS Browser Source.
- **Watching Japanese livestreams & videos** — capture tab audio and get live Japanese captions plus an English translation while you watch.
- **Japanese learning & listening practice** — read along with live captions and translations for videos, podcasts, and live streams.
- **Microphone capture** — run real-time Japanese ASR and translation on your own speech for practice or content.

## Demo

Feature demos are stored in `demo/`. Click a thumbnail to play the video:

**Transparent desktop overlay**

[![crisp-caption transparent desktop overlay demo](demo/ControlPanel.png)](demo/overlay.mp4)

**OBS subtitle overlay**

[![crisp-caption OBS subtitle overlay demo](demo/ControlPanel.png)](demo/obs-subtitle.mp4)

> Full demo page and notes: [demo/](demo/README.md)

## Windows Quick Start

From the project folder, run the single console that replaces the old per-step scripts:

```bat
crisp-caption.bat
```

Choose from the menu:

- `1` full setup (create `.venv` + install Python deps)
- `2` download CrispASR / llama.cpp / models
- `3` check dependencies
- `4` start (Local / Colab / Diagnostics)

Then open:

```text
http://127.0.0.1:8765/
```

In the browser UI, choose:

- `Tab audio` for video playback or livestream watching in a browser tab.
- `Microphone` for microphone capture.
- `Overlay` for a transparent always-on-top subtitle window.

On Chromium-based browsers, enable tab audio in the browser capture picker.

## What The Console Does

`crisp-caption.bat` is the single entry point. Its menu wraps the previous per-step scripts:

- `1` **Setup** — checks Python/pip, creates `.venv`, installs `requirements.txt` and `requirements-overlay.txt`. Browser UI is `static\index.html` (no Node build).
- `2` **Download** — submenu: download CrispASR (CUDA if NVIDIA/CUDA, else Vulkan), llama.cpp, the models from `models\manifest.json`, or all three.
- `3` **Check** — runs `scripts\check_deps.py` (Python packages, profile, CrispASR, llama.cpp, models, ports, translation reachability).
- `4` **Start** — submenu: Local (start llama.cpp translation server + bridge), Colab (open the Web UI and use Connect), or Diagnostics (`-v`).

The old per-step scripts were moved to `scripts\deprecate\` for reference; the console is the supported path.

## Hardware And Runtime

The default path uses Vulkan for both CrispASR and llama.cpp.

Recommended baseline:

- Windows 10 or 11
- Vulkan-capable GPU
- About 6 GB VRAM
- Python 3.11+
- Chromium-based browser for tab audio capture

If the translation server exits immediately or runs out of memory, set the environment variable before starting:

```bat
set LOW_VRAM=1
scripts\start-translation-server-windows.bat
```

Low-VRAM mode uses smaller llama.cpp context/batch settings (`-c 4096 -b 512 -ub 256`). It may be slower or have less translation context.

## Colab / Kaggle Remote Compute

Remote mode keeps the browser UI, WebRTC capture, OBS overlay, and transparent overlay on Windows, but sends 16 kHz mono PCM to a Colab- or Kaggle-hosted CrispASR service and sends final subtitles to a Colab- or Kaggle-hosted llama.cpp server.

1. In Colab or Kaggle, open `scripts/colab/crisp_caption_colab_remote.ipynb`. The notebook auto-detects the platform and `git clone`s this repo for you — no file upload needed.
2. Run the notebook cells in order. The notebook clones the project, downloads cloudflared, model files, a Linux CrispASR release, and a prebuilt llama.cpp release when possible. Set `LLAMA_BACKEND=auto`, `ai-dock-cuda`, `vulkan`, `official-cpu`, or `build-cuda` to choose the translation runtime. If auto-detection fails, set `CRISPASR_URL`, `CRISPASR_EXE`, `LLAMA_CPP_URL`, or `LLAMA_SERVER`.
3. Run the final notebook cell. It starts llama.cpp, starts the ASR/translation proxy, starts Cloudflare Tunnel, and shows the token and tunnel URL as large, click-to-select boxes so you can copy them easily without a Copy button.

The helper no longer builds llama.cpp by default. Use `python scripts/colab/run_colab_remote.py --build-llama` only when you intentionally want a source-build fallback.

The script prints the values you need to connect your Windows side:

```text
CRISPASR_REMOTE_KEY=...
https://<host>.trycloudflare.com
```

On Windows, open `http://127.0.0.1:8765/`, click **Connect**, pick the profile, choose Local or Notebook/Remote under ASR and Translation, and paste the WebSocket URL / translation URL and the two keys printed by Colab. Nothing is saved to the profile file — the values apply for this session only.

Manual equivalent:

```bat
set CRISPASR_REMOTE_KEY=<ASR key printed by Colab>
set OPENAI_API_KEY=<translation key printed by Colab>
crisp-caption.bat
```
then choose `4` → `2` Colab to start.

`OPENAI_API_KEY` is used as the Bearer token for the remote llama.cpp proxy. Cloudflare Tunnel URLs are ephemeral, so re-enter them whenever the Colab runtime restarts.

> Note: Kaggle support assumes the Kaggle notebook environment can establish an outbound Cloudflare Tunnel like Colab does. Verify this on the first run if you use Kaggle.


## Models

The default profile expects:

```text
models\asr\cohere-asr-ja-q6_k.gguf
models\vad\firered-vad.gguf
models\translation\Hy-MT2-1.8B-Q4_K_M.gguf
```

`models\manifest.json` uses pinned Hugging Face `resolve` URLs with SHA256 verification. Model payloads are ignored by Git.

Hy-MT2 uses the Tencent HY Community License Agreement, not a permissive open-source license. Read `docs\third-party.md` and the upstream license before redistribution or commercial use.

## Profiles

Public profiles live in `profiles\`:

```text
profiles\profile-stable-ja.jsonc
profiles\profile.ja.colab.jsonc
profiles\profile-low-latency.jsonc
```

Pick one as your active profile in the Web UI. Any local-only profiles you keep are ignored by Git.

Local profile JSON files are ignored by Git. Edit `profiles\profile.ja.json` for your machine.

Important fields:

```json
"asr_mode": "local",
"crispasr": "tools/crispasr/crispasr.exe",
"translate_model": "Hy-MT2-1.8B",
"translate_url": "http://127.0.0.1:8080/v1/chat/completions"
```

Model paths in `crisp_args`, such as `../models/asr/model.gguf`, are resolved relative to the profile JSON file.

## Transparent Overlay

Click `Overlay` in the browser UI to start the native transparent subtitle overlay.

Controls:

- Hold `Ctrl` to show the control frame.
- Hold `Ctrl` and drag the middle area to move the overlay.
- Hold `Ctrl` and drag the handles to resize it.
- Hold `Ctrl` and scroll to resize the subtitle text.
- Hold `Ctrl` and click `x` to close it.
- `Ctrl+Q` also closes the overlay.

Overlay position, size, and font size are remembered across restarts in `~\.crispasr-overlay.json`. Click `Stop Overlay` in the browser UI to close it.

## OBS Overlay

For OBS, use a Browser Source:

```text
http://127.0.0.1:8765/obs-overlay
```

Set the Browser Source size to your canvas size, for example `1920 x 1080`. The page has a transparent background and connects to the same subtitle stream.

Query parameters:

- `mode=both|source|trans` — show both lines, source only, or translation only (default `both`, falls back to source when no translation).
- `pos=bottom|top` — subtitle position (default `bottom`).
- `hold=<sec>` — minimum seconds a line stays before the next may replace it (default `2`).
- `fade=<sec>` — seconds of inactivity before fading out, `0` = never (default `4`).
- `font=<scale>` — text size scale relative to the default (default `1`).
- `demo=1` — show sample subtitles without a running bridge.

## Translation Server

The default translation server command is in:

```bat
scripts\start-translation-server-windows.bat
```

It uses llama.cpp Vulkan with:

```text
-c 8192 -b 2048 -ub 1024
```

The profile model name must match the llama.cpp alias:

```json
"translate_model": "Hy-MT2-1.8B"
```

Translation is final-only. Partial ASR text is shown as live preview but is not sent to the translation model.

## Troubleshooting

Run:

```bat
crisp-caption.bat
```
then choose `3` check dependencies.

Common fixes:

- Missing Python packages: run `crisp-caption.bat` → `1` setup.
- Missing CrispASR: run `crisp-caption.bat` → `2` download CrispASR.
- Missing llama.cpp: run `crisp-caption.bat` → `2` download llama.cpp.
- Missing models: run `crisp-caption.bat` → `2` download models.
- Translation server out of memory: use `set LOW_VRAM=1 && scripts\start-translation-server-windows.bat`.
- Remote Colab 401/unauthorized: set `CRISPASR_REMOTE_KEY` for ASR and `OPENAI_API_KEY` for translation.
- Remote Colab connection failure: refresh the Cloudflare Tunnel URLs in the selected Colab profile (`profiles\profile.ja.colab.jsonc`).
- Browser UI missing: ensure `static\index.html` exists.

## Development

Edit `static\index.html`, `static\app.css`, `static\app.js` and hard-refresh. No build step.

## Debug Commands

Use the virtual environment Python after setup:

```bat
.venv\Scripts\python.exe bridge_server.py --config profiles\profile-stable-ja.jsonc --print-raw-crisp-events
.venv\Scripts\python.exe bridge_server.py --config profiles\profile-stable-ja.jsonc --no-translate
.venv\Scripts\python.exe bridge_server.py --config profiles\profile-stable-ja.jsonc --no-translate --debug-timestamps
.venv\Scripts\python.exe bridge_server.py --config profiles\profile-stable-ja.jsonc -v
```

## Documentation

- `docs\PARAMETERS.md`: profile and CrispASR flag reference.
- `docs\third-party.md`: third-party runtime and model license notes.
- `profiles\profile-stable-ja.jsonc`: Japanese stable profile (local + Colab).
- `profiles\profile.ja.colab.jsonc`: Japanese Colab remote profile.
- `profiles\profile-low-latency.jsonc`: low-latency Japanese profile.

## License

`crisp-caption` source code is licensed under the Apache License 2.0. Runtime binaries and model files downloaded by the helper scripts are third-party artifacts under their own licenses. See `docs\third-party.md`.

---

**Read this in another language:** [繁體中文](README.zh-TW.md) | English