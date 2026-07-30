# Third-Party Runtime And Model Licenses

`crisp-caption` source code is licensed under the Apache License 2.0 in `LICENSE`.

The setup and download scripts may download third-party runtime binaries and model files. Those files are not part of this repository's Apache-2.0 license. They remain under their own licenses and terms.

## Runtime Binaries

- CrispASR: downloaded by `scripts/download-crispasr-windows.bat`.
  - Project: https://github.com/CrispStrobe/CrispASR
  - License: MIT, according to the upstream `LICENSE`.
- llama.cpp: downloaded by `scripts/download-llama-cpp-windows.bat`.
  - Project: https://github.com/ggml-org/llama.cpp
  - License: MIT, according to the upstream `LICENSE`.
- cloudflared: downloaded by the optional Colab helper script.
  - Project: https://github.com/cloudflare/cloudflared
  - License: Apache License 2.0, according to the upstream `LICENSE`.

## Model Files

Model payloads are downloaded by `scripts/models-download.bat` from the URLs listed in `models/manifest.json`.

- `TransWithAI/cohere-transcribe-ja-v0.1-GGUF`
  - URL: https://huggingface.co/TransWithAI/cohere-transcribe-ja-v0.1-GGUF
  - Note: the model card says the base Cohere Transcribe model is Apache-2.0, but the Japanese fine-tune repository did not declare an explicit license at conversion time. Check the source model card before redistribution or commercial use.
- `cstr/firered-vad-GGUF`
  - URL: https://huggingface.co/cstr/firered-vad-GGUF
  - License: Apache-2.0, according to the model card.
- `tencent/Hy-MT2-1.8B-GGUF`
  - URL: https://huggingface.co/tencent/Hy-MT2-1.8B-GGUF
  - License: Tencent HY Community License Agreement.
  - Upstream license text: https://github.com/Tencent-Hunyuan/Hy-MT2/blob/main/LICENSE.txt
  - Important notes from the upstream license: it does not apply in the European Union; distribution requires providing the license agreement and a notice file; large commercial services may require a separate Tencent license; usage is subject to the acceptable use policy. Read the upstream license before downloading, redistributing, or using this model commercially.

If you redistribute a release bundle containing downloaded runtime binaries or model files, include the applicable third-party license notices and verify that each model license allows your intended use.
