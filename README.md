# crisp-caption

Live Japanese captions and translation for browser audio, video playback, livestream watching, and OBS.

The target setup is a Windows PC with a Vulkan-capable GPU and about 6 GB of VRAM. With the default Japanese ASR + Hy-MT2 translation profile, the intended live delay is roughly within 5 seconds on suitable hardware.

`crisp-caption` captures tab or microphone audio in the browser, streams it to CrispASR, translates finalized utterances with a local llama.cpp server, and displays subtitles in the browser, a transparent desktop overlay, or an OBS Browser Source.

```text
browser tab/mic audio
  -> WebRTC
  -> Python bridge
  -> CrispASR Vulkan streaming ASR, local or remote Colab WebSocket
  -> llama.cpp translation server, local or remote Colab HTTP
  -> browser transcript / transparent overlay / OBS overlay
```

This repository does not vendor runtime binaries or model files. The setup scripts download GPU-accelerated builds (CUDA if available, else Vulkan) into `tools/` and model files into `models/`.

## Demo

Feature demos are stored in `demo/`:

![Control panel](demo/ControlPanel.png)

- [Transparent desktop overlay](demo/overlay.mp4)
- [OBS subtitle overlay](demo/obs-subtitle.mp4)
- [Full demo page](demo/)

The demo page includes GitHub-hosted video previews and local MP4 fallbacks.

## Windows Quick Start

Run these commands from the project folder:

```bat
scripts\setup-windows.bat
scripts\download-crispasr-windows.bat
scripts\download-llama-cpp-windows.bat
scripts\models-download.bat
scripts\check-deps.bat
scripts\run-windows.bat
```

Then open:

```text
http://127.0.0.1:8765/
```

In the browser UI, choose:

- `Tab audio` for video playback or livestream watching in a browser tab.
- `Microphone` for microphone capture.
- `Overlay` for a transparent always-on-top subtitle window.

On Chromium-based browsers, enable tab audio in the browser capture picker.

## What The Scripts Do

`scripts\setup-windows.bat`

- Checks Python and pip.
- Creates `.venv`.
- Installs Python dependencies.
- Installs transparent overlay dependencies.
- Creates `profiles\profile.ja.json` from `profiles\profile.ja.example.json` if missing.
- Browser UI is `static\index.html` (no Node build).

`scripts\download-crispasr-windows.bat`

- Downloads the latest CrispASR Windows runtime from GitHub (CUDA if the machine has NVIDIA/CUDA, else Vulkan).
- Extracts it to `tools\crispasr\`.
- Deletes the downloaded archive.
- Checks that `tools\crispasr\crispasr.exe` starts.

`scripts\download-llama-cpp-windows.bat`

- Downloads the latest llama.cpp Windows runtime from GitHub (CUDA if available, else Vulkan; CUDA also pulls matching cudart).
- Extracts it to `tools\llama.cpp\`.
- Deletes the downloaded archive.
- Checks that `tools\llama.cpp\llama-server.exe` exists.

`scripts\models-download.bat`

- Downloads the ASR model, VAD model, and Hy-MT2 translation model listed in `models\manifest.json`.
- Stores model files under `models\`.

`scripts\check-deps.bat`

- Checks Python packages, control UI module, profile, CrispASR, llama.cpp, model files, ports, and translation server reachability.

`scripts\run-windows.bat`

- Starts the llama.cpp translation server in a separate window if the local model and binary exist and the server is not already running.
- Opens `http://127.0.0.1:8765/` (profile selection starts the bridge on first connect).
- Uses `scripts\_run_py.bat` to resolve the Python interpreter from `.venv`.

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

## Colab Remote Compute

Remote mode keeps the browser UI, WebRTC capture, OBS overlay, and transparent overlay on Windows, but sends 16 kHz mono PCM to a Colab-hosted CrispASR service and sends final subtitles to a Colab-hosted llama.cpp server.

1. In Colab, open or upload `scripts/colab/crisp_caption_colab_remote.ipynb`.
2. Upload `scripts/colab/run_colab_remote.py` when the notebook asks for it.
3. The helper automatically downloads cloudflared, model files, a Linux CrispASR release, and a prebuilt llama.cpp release when possible. Set `LLAMA_BACKEND=auto`, `ai-dock-cuda`, `vulkan`, `official-cpu`, or `build-cuda` to choose the translation runtime. If auto-detection fails, set `CRISPASR_URL`, `CRISPASR_EXE`, `LLAMA_CPP_URL`, or `LLAMA_SERVER`.
4. Run the final notebook cell, or run the helper script directly:

```bash
python run_colab_remote.py
```

The helper no longer builds llama.cpp by default. Use `python run_colab_remote.py --build-llama` only when you intentionally want a source-build fallback.

The script starts llama.cpp, starts the ASR/translation proxy on Colab, starts Cloudflare Tunnel, and prints:

```text
CRISPASR_REMOTE_TOKEN=...
https://<host>.trycloudflare.com
```

On Windows, copy `profiles\profile.ja.colab.example.json` to `profiles\profile.ja.json`, then set:

```json
"remote_asr_url": "wss://<host>.trycloudflare.com/asr/stream",
"translate_url": "https://<host>.trycloudflare.com/v1/chat/completions"
```

Set the token in the same terminal before starting the bridge, or use the helper script:

```bat
colab-token.bat
```

The helper prompts for the token, sets both `CRISPASR_REMOTE_TOKEN` and `OPENAI_API_KEY`, then launches the bridge.

Manual equivalent:

```bat
set CRISPASR_REMOTE_TOKEN=<token printed by Colab>
set OPENAI_API_KEY=<same token>
scripts\check-deps.bat
scripts\run-windows.bat
```

`OPENAI_API_KEY` is used as the Bearer token for the remote llama.cpp proxy. Cloudflare Tunnel URLs are ephemeral, so update the profile whenever the Colab runtime restarts.

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

Public example profiles live in `profiles\`.

```text
profiles\profile.ja.example.json
```

`setup-windows.bat` copies it to:

```text
profiles\profile.ja.json
```

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
- Hold `Ctrl` and click `x` to close it.
- `Ctrl+Q` also closes the overlay.

## OBS Overlay

For OBS, use a Browser Source:

```text
http://127.0.0.1:8765/obs-overlay
```

Set the Browser Source size to your canvas size, for example `1920 x 1080`. The page has a transparent background and connects to the same subtitle stream.

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
scripts\check-deps.bat
```

Common fixes:

- Missing Python packages: run `scripts\setup-windows.bat`.
- Missing CrispASR: run `scripts\download-crispasr-windows.bat`.
- Missing llama.cpp: run `scripts\download-llama-cpp-windows.bat`.
- Missing models: run `scripts\models-download.bat`.
- Translation server out of memory: use `set LOW_VRAM=1 && scripts\start-translation-server-windows.bat`.
- Remote Colab 401/unauthorized: set `CRISPASR_REMOTE_TOKEN` for ASR and `OPENAI_API_KEY` for translation.
- Remote Colab connection failure: refresh the Cloudflare Tunnel URLs in `profiles\profile.ja.json`.
- Browser UI missing: ensure `static\index.html` exists.

## Development

Edit `static\index.html`, `static\app.css`, `static\app.js` and hard-refresh. No build step.

## Debug Commands

Use the virtual environment Python after setup:

```bat
.venv\Scripts\python.exe bridge_server.py --config profiles\profile.ja.json --print-raw-crisp-events
.venv\Scripts\python.exe bridge_server.py --config profiles\profile.ja.json --no-translate
.venv\Scripts\python.exe bridge_server.py --config profiles\profile.ja.json --no-translate --debug-timestamps
.venv\Scripts\python.exe bridge_server.py --config profiles\profile.ja.json -v
```

## Documentation

- `docs\PARAMETERS.md`: profile and CrispASR flag reference.
- `docs\third-party.md`: third-party runtime and model license notes.
- `profiles\profile.ja.example.json`: public Japanese live-subtitle example profile.
- `profiles\profile.ja.colab.example.json`: public Japanese Colab remote example profile.

## License

`crisp-caption` source code is licensed under the Apache License 2.0. Runtime binaries and model files downloaded by the helper scripts are third-party artifacts under their own licenses. See `docs\third-party.md`.
