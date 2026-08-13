# crisp-caption

**即時日文字幕與翻譯 — 在瀏覽器影片、直播、OBS 上即時顯示，並在你的 GPU 上本地執行。**

crisp-caption 在瀏覽器中擷取分頁或麥克風音訊，串流到 CrispASR（Vulkan 加速的串流語音辨識），以本地 llama.cpp 伺服器翻譯最終語句，並在瀏覽器、透明桌面浮窗或 OBS Browser Source 中顯示字幕。

目標環境是配備支援 Vulkan 的 GPU 與約 6 GB VRAM 的 Windows PC。搭配預設的日文 ASR + Hy-MT2 翻譯設定檔，在合適硬體上預期的直播延遲約在 5 秒內。

```text
browser tab/mic audio
  -> WebRTC
  -> Python bridge
  -> CrispASR Vulkan streaming ASR, local or remote Colab WebSocket
  -> llama.cpp translation server, local or remote Colab HTTP
  -> browser transcript / transparent overlay / OBS overlay
```

本倉庫不隨附執行檔或模型檔案。設定腳本會將 GPU 加速版本（如可用則用 CUDA，否則用 Vulkan）下載到 `tools/`，模型檔案下載到 `models/`。

## 功能特色 (Features)

- **即時日文語音辨識 (ASR)** — 將瀏覽器分頁或麥克風音訊串流到 CrispASR，進行即時語音辨識，支援部分（預覽）與最終結果。
- **日文翻譯（可翻成英文等多種語言）** — 使用本地 llama.cpp 伺服器（Hy-MT2 模型）自動翻譯最終語句。
- **透明桌面浮窗** — 點擊穿透、永遠置頂的字幕視窗，可用 `Ctrl` 移動、縮放與調整樣式。
- **OBS Browser Source 字幕** — 將字幕串流以透明 Browser Source 直接匯入 OBS，適合直播。
- **低延遲本地推論** — Vulkan 加速的 ASR 與 LLM 翻譯，在消費級 GPU 上約 5 秒的直播延遲。
- **遠端 Colab / Kaggle 運算** — 沒有高階 GPU 時，可透過 Cloudflare Tunnel 將 ASR 與翻譯卸載到免費的 Colab 或 Kaggle notebook。
- **單一控制台入口** — `crisp-caption.bat` 一次處理安裝、下載、依賴檢查與啟動。

## 使用情境 (Use Cases)

- **OBS 即時日文字幕** — 使用透明的 OBS Browser Source，為你的直播或 VOD 加上即時日文字幕。
- **觀看日文直播與影片** — 擷取分頁音訊，在觀看時即時取得日文字幕及英文翻譯。
- **日文學習與聽力練習** — 邊看邊讀影片、Podcast、直播的即時字幕與翻譯。
- **麥克風收音** — 對你自己的說話內容執行即時日文 ASR 與翻譯，用於練習或內容創作。

## Demo 展示

功能示範存放在 `demo/`。點擊縮圖即可播放影片：

**透明桌面浮窗**

[![crisp-caption 透明桌面浮窗示範](demo/ControlPanel.png)](demo/overlay.mp4)

**OBS 字幕浮窗**

[![crisp-caption OBS 字幕浮窗示範](demo/ControlPanel.png)](demo/obs-subtitle.mp4)

> 完整 demo 頁面與說明： [demo/](demo/README.md)

## Windows 快速開始

在專案資料夾中，執行取代舊版各步驟腳本的單一控制台：

```bat
crisp-caption.bat
```

從選單選擇：

- `1` 完整安裝（建立 `.venv` + 安裝 Python 依賴）
- `2` 下載 CrispASR / llama.cpp / models
- `3` 檢查依賴
- `4` 啟動（Local / Colab / Diagnostics）

然後開啟：

```text
http://127.0.0.1:8765/
```

在瀏覽器介面中選擇：

- `Tab audio` 用於在瀏覽器分頁中播放影片或觀看直播。
- `Microphone` 用於麥克風收音。
- `Overlay` 用於透明、永遠置頂的字幕視窗。

在 Chromium 系瀏覽器中，請在瀏覽器擷取選取器中啟用分頁音訊。

## 控制台功能說明

`crisp-caption.bat` 是單一入口點，它的選單包裝了舊版的各步驟腳本：

- `1` **Setup 安裝** — 檢查 Python/pip，建立 `.venv`，安裝 `requirements.txt` 與 `requirements-overlay.txt`。瀏覽器介面是 `static\index.html`（無需 Node 建置）。
- `2` **Download 下載** — 子選單：下載 CrispASR（NVIDIA/CUDA 用 CUDA，否則用 Vulkan）、llama.cpp、`models\manifest.json` 中的模型，或全部三項。
- `3` **Check 檢查** — 執行 `scripts\check_deps.py`（Python 套件、設定檔、CrispASR、llama.cpp、模型、連接埠、翻譯可達性）。
- `4` **Start 啟動** — 子選單：Local（啟動 llama.cpp 翻譯伺服器 + bridge）、Colab（開啟 Web UI 並使用 Connect）、或 Diagnostics（`-v`）。

舊版的各步驟腳本已移至 `scripts\deprecate\` 供參考；控制台是受支援的途徑。

## 硬體與執行環境

預設路徑對 CrispASR 與 llama.cpp 都使用 Vulkan。

建議的基準環境：

- Windows 10 或 11
- 支援 Vulkan 的 GPU
- 約 6 GB VRAM
- Python 3.11+
- 用於分頁音訊收音的 Chromium 系瀏覽器

如果翻譯伺服器立即結束或記憶體不足，請在啟動前設定環境變數：

```bat
set LOW_VRAM=1
scripts\start-translation-server-windows.bat
```

低 VRAM 模式使用較小的 llama.cpp context/batch 設定（`-c 4096 -b 512 -ub 256`）。可能會較慢，或翻譯上下文較少。

## Colab / Kaggle 遠端運算

遠端模式在 Windows 端保留瀏覽器介面、WebRTC 收音、OBS 浮窗與透明浮窗，但將 16 kHz 單聲道 PCM 傳送到 Colab 或 Kaggle 託管的 CrispASR 服務，並將最終字幕傳送到 Colab 或 Kaggle 託管的 llama.cpp 伺服器。

1. 在 Colab 或 Kaggle 開啟 `scripts/colab/crisp_caption_colab_remote.ipynb`。notebook 會自動偵測平台，並為你 `git clone` 此 repo — 無需上傳檔案。
2. 依序執行 notebook 的 cell。notebook 會複製專案、下載 cloudflared、模型檔案、Linux CrispASR 版本，並在可能時下載預先編譯的 llama.cpp 版本。設定 `LLAMA_BACKEND=auto`、`ai-dock-cuda`、`vulkan`、`official-cpu` 或 `build-cuda` 以選擇翻譯執行環境。若自動偵測失敗，可設定 `CRISPASR_URL`、`CRISPASR_EXE`、`LLAMA_CPP_URL` 或 `LLAMA_SERVER`。
3. 執行最後一個 notebook cell。它會啟動 llama.cpp、啟動 ASR/翻譯 proxy、啟動 Cloudflare Tunnel，並將 token 與 tunnel URL 顯示為大型、可點選複製的方塊，方便你直接複製。

Helper 預設不再編譯 llama.cpp。只有在你有意使用原始碼編譯作為備援時，才使用 `python scripts/colab/run_colab_remote.py --build-llama`。

腳本會印出連接 Windows 端所需的數值：

```text
CRISPASR_REMOTE_KEY=...
https://<host>.trycloudflare.com
```

在 Windows 端，開啟 `http://127.0.0.1:8765/`，點擊 **Connect**，選擇設定檔，在 ASR 與 Translation 下選擇 Local 或 Notebook/Remote，然後貼上 Colab 印出的 WebSocket URL / 翻譯 URL 與兩個 key。這些值不會存入設定檔 — 僅適用於本次工作階段。

手動方式：

```bat
set CRISPASR_REMOTE_KEY=<Colab 印出的 ASR key>
set OPENAI_API_KEY=<Colab 印出的翻譯 key>
crisp-caption.bat
```
然後選擇 `4` → `2` Colab 啟動。

`OPENAI_API_KEY` 用作遠端 llama.cpp proxy 的 Bearer token。Cloudflare Tunnel URL 是臨時的，因此每當 Colab 執行環境重新啟動時都必須重新輸入。

> 注意：Kaggle 支援假設 Kaggle notebook 環境能像 Colab 一樣建立對外的 Cloudflare Tunnel。若使用 Kaggle，請在首次執行時驗證。

## 模型 (Models)

預設設定檔預期：

```text
models\asr\cohere-asr-ja-q6_k.gguf
models\vad\firered-vad.gguf
models\translation\Hy-MT2-1.8B-Q4_K_M.gguf
```

`models\manifest.json` 使用固定的 Hugging Face `resolve` URL，並以 SHA256 驗證。模型檔案會被 Git 忽略。

Hy-MT2 使用騰訊 HY Community License Agreement，而非寬鬆的開源授權。在重新散布或商業使用前，請閱讀 `docs\third-party.md` 與上游授權。

## 設定檔 (Profiles)

公開設定檔位於 `profiles\`：

```text
profiles\profile-stable-ja.jsonc
profiles\profile.ja.colab.jsonc
profiles\profile-low-latency.jsonc
```

在 Web UI 中選擇一個作為啟用中的設定檔。你保留的僅限本機設定檔會被 Git 忽略。

本機設定檔 JSON 檔案會被 Git 忽略。請為你的機器編輯 `profiles\profile.ja.json`。

重要欄位：

```json
"asr_mode": "local",
"crispasr": "tools/crispasr/crispasr.exe",
"translate_model": "Hy-MT2-1.8B",
"translate_url": "http://127.0.0.1:8080/v1/chat/completions"
```

`crisp_args` 中的模型路徑（例如 `../models/asr/model.gguf`）會相對於設定檔 JSON 檔案解析。

## 透明浮窗 (Transparent Overlay)

在瀏覽器介面中點擊 `Overlay` 以啟動原生透明字幕浮窗。

控制方式：

- 按住 `Ctrl` 顯示控制框。
- 按住 `Ctrl` 並拖曳中間區域以移動浮窗。
- 按住 `Ctrl` 並拖曳控制點以縮放。
- 按住 `Ctrl` 並捲動以調整字幕文字大小。
- 按住 `Ctrl` 並點擊 `x` 關閉。
- `Ctrl+Q` 也會關閉浮窗。

浮窗的位置、大小與字型大小會在 `~\.crispasr-overlay.json` 中跨重新啟動記憶。在瀏覽器介面中點擊 `Stop Overlay` 關閉它。

## OBS 浮窗 (OBS Overlay)

對 OBS 使用 Browser Source：

```text
http://127.0.0.1:8765/obs-overlay
```

將 Browser Source 尺寸設為你的畫布尺寸，例如 `1920 x 1080`。該頁面有透明背景，並連接到相同的字幕串流。

查詢參數：

- `mode=both|source|trans` — 顯示兩行、僅原文、或僅翻譯（預設 `both`，無翻譯時退回原文）。
- `pos=bottom|top` — 字幕位置（預設 `bottom`）。
- `hold=<sec>` — 一行至少停留的秒數，之後才允許下一行替換（預設 `2`）。
- `fade=<sec>` — 無活動幾秒後淡出，`0` = 永不淡出（預設 `4`）。
- `font=<scale>` — 相對於預設的文字大小比例（預設 `1`）。
- `demo=1` — 在未執行 bridge 時顯示示範字幕。

## 翻譯伺服器 (Translation Server)

預設翻譯伺服器命令位於：

```bat
scripts\start-translation-server-windows.bat
```

它使用 llama.cpp Vulkan：

```text
-c 8192 -b 2048 -ub 1024
```

設定檔模型名稱必須符合 llama.cpp 別名：

```json
"translate_model": "Hy-MT2-1.8B"
```

翻譯僅針對最終語句。部分 ASR 文字會以即時預覽顯示，但不會傳送給翻譯模型。

## 疑難排解 (Troubleshooting)

執行：

```bat
crisp-caption.bat
```
然後選擇 `3` 檢查依賴。

常見修正：

- 缺少 Python 套件：執行 `crisp-caption.bat` → `1` 安裝。
- 缺少 CrispASR：執行 `crisp-caption.bat` → `2` 下載 CrispASR。
- 缺少 llama.cpp：執行 `crisp-caption.bat` → `2` 下載 llama.cpp。
- 缺少模型：執行 `crisp-caption.bat` → `2` 下載模型。
- 翻譯伺服器記憶體不足：使用 `set LOW_VRAM=1 && scripts\start-translation-server-windows.bat`。
- 遠端 Colab 401/未授權：為 ASR 設定 `CRISPASR_REMOTE_KEY`，為翻譯設定 `OPENAI_API_KEY`。
- 遠端 Colab 連線失敗：在所選的 Colab 設定檔（`profiles\profile.ja.colab.jsonc`）中重新整理 Cloudflare Tunnel URL。
- 瀏覽器介面遺失：確認 `static\index.html` 存在。

## 開發 (Development)

編輯 `static\index.html`、`static\app.css`、`static\app.js` 並強制重新整理。無需建置步驟。

## 除錯指令 (Debug Commands)

安裝後使用虛擬環境 Python：

```bat
.venv\Scripts\python.exe bridge_server.py --config profiles\profile-stable-ja.jsonc --print-raw-crisp-events
.venv\Scripts\python.exe bridge_server.py --config profiles\profile-stable-ja.jsonc --no-translate
.venv\Scripts\python.exe bridge_server.py --config profiles\profile-stable-ja.jsonc --no-translate --debug-timestamps
.venv\Scripts\python.exe bridge_server.py --config profiles\profile-stable-ja.jsonc -v
```

## 文件 (Documentation)

- `docs\PARAMETERS.md`：設定檔與 CrispASR 旗標參考。
- `docs\third-party.md`：第三方執行環境與模型授權說明。
- `profiles\profile-stable-ja.jsonc`：日文穩定設定檔（Local + Colab）。
- `profiles\profile.ja.colab.jsonc`：日文 Colab 遠端設定檔。
- `profiles\profile-low-latency.jsonc`：低延遲日文設定檔。

## 授權 (License)

`crisp-caption` 原始碼以 Apache License 2.0 授權。由 helper 腳本下載的執行檔與模型檔案是第三方產物，受各自授權規範。詳見 `docs\third-party.md`。

---

**以其他語言閱讀：** [English](README.md) | 繁體中文