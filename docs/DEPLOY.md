<!-- LANG-SWITCH -->
**English** | [中文](DEPLOY.zh.md)

# SuwayomiOCR — Deployment Guide

This document covers both **bare-metal** and **Docker** deployment, and how
to swap the OCR / translation backends to any OpenAI-compatible provider.

- [Recommended setup (TL;DR)](#recommended-setup-tldr)
- [Hosted DeepSeek-OCR-2 providers (no GPU needed)](#hosted-deepseek-ocr-2-providers-no-gpu-needed)
- [Quick choice](#quick-choice)
- [Option A — Bare metal (venv)](#option-a--bare-metal-venv)
- [Option B — Docker (single image)](#option-b--docker-single-image)
- [Option C — Docker Compose](#option-c--docker-compose)
- [Configuration reference](#configuration-reference)
- [Swapping the OCR backend](#swapping-the-ocr-backend)
- [Swapping the translation backend](#swapping-the-translation-backend)
- [SuwayomiGO client setup](#suwayomigo-client-setup)
- [Production tips](#production-tips)

---

## Recommended setup (TL;DR)

The combination that **scored best in our benchmark** ([BENCHMARKS.md](BENCHMARKS.md)):

| Stage | Model | Where it runs |
|---|---|---|
| **OCR** | [`deepseek-ai/DeepSeek-OCR-2`](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2) (3 B params, BF16, ~7 GB VRAM) | Local vLLM (one GPU is enough) |
| **Translation** | `deepseek-v4-flash` | DeepSeek cloud (≈ ¥2.5 / 1000 pages) |

Why this combo: DeepSeek-OCR-2 is a specialised OCR model that outperforms
generic vision LLMs on dense manga text; `deepseek-v4-flash` is a
manga-aware chat model that wins on BLEU/chrF in our [benchmark](BENCHMARKS.md)
and is cheap enough to be effectively free for personal use.

### Step 1 — Get a DeepSeek API key

1. Sign up at **<https://platform.deepseek.com>**.
2. Open **<https://platform.deepseek.com/api_keys>** and click *Create new key*.
3. Top up RMB 5–10 — it covers thousands of pages, more than personal use needs.
4. Copy the key (`sk-...`). You'll paste it into `.env` in Step 3.

### Step 2 — Run DeepSeek-OCR-2 via vLLM (one-time, on a machine with a GPU)

Repo: <https://github.com/deepseek-ai/DeepSeek-OCR-2>. The model is ~6 GB; it
auto-downloads from HuggingFace on first launch.

```bash
# Need: a clean conda/venv env, Python 3.11+, an NVIDIA GPU with ≥ 8 GB VRAM,
# CUDA driver, and ~15 GB free disk for the HF cache.
pip install "vllm>=0.8.5"

# Optional but recommended: cache HF weights on a fast disk
export HF_HOME=/path/to/hf-cache

# Start vLLM — listens on :19260 (matches the SuwayomiOCR .env default)
CUDA_VISIBLE_DEVICES=0 \
vllm serve deepseek-ai/DeepSeek-OCR-2 \
  --host 0.0.0.0 \
  --port 19260 \
  --trust-remote-code \
  --max-model-len 8192
```

Wait for `Application startup complete.` Then verify:
```bash
curl -s http://127.0.0.1:19260/v1/models | python3 -m json.tool
# → should list "deepseek-ai/DeepSeek-OCR-2"
```

> **No local GPU?** Either use a hosted DeepSeek-OCR-2 endpoint (see
> [providers below](#hosted-deepseek-ocr-2-providers-no-gpu-needed) — keeps the OCR quality
> identical) or swap to a general vision LLM (GPT-4o-mini, Qwen-VL-Max …)
> per [Swapping the OCR backend](#swapping-the-ocr-backend).

### Step 3 — Configure `.env`

```bash
cp .env.example .env
$EDITOR .env
```

Set these four lines (defaults are correct except `TRANSLATION_API_KEY`):
```dotenv
OCR_API_BASE_URL=http://127.0.0.1:19260/v1
OCR_API_MODEL=deepseek-ai/DeepSeek-OCR-2

TRANSLATION_API_BASE_URL=https://api.deepseek.com/v1
TRANSLATION_API_MODEL=deepseek-v4-flash
TRANSLATION_API_KEY=sk-paste-your-key-here
```

### Step 4 — Run the SuwayomiOCR server

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m suwayomi_ocr
```

You should see:
```
[*] translation API client initialized (model=deepseek-v4-flash)
[*] OCR backend reachable at http://127.0.0.1:19260/v1
[*] SuwayomiOCR listening on http://<your-LAN-ip>:12233
```

Done — point your SuwayomiGO app at `http://<your-LAN-ip>:12233`. See
[SuwayomiGO client setup](#suwayomigo-client-setup) for the two settings to
fill in on the phone.

---

## Hosted DeepSeek-OCR-2 providers (no GPU needed)

If you can't (or don't want to) run vLLM yourself, several third-party
platforms host DeepSeek-OCR-2 as an OpenAI-compatible API. The open-source
model id is **`deepseek-ai/DeepSeek-OCR-2`**; most third-party providers
publish it as **`deepseek/deepseek-ocr-2`**.

Surveyed **2026-05-22**. Always check the provider's console for the
current model id and exact base URL before pasting into `.env`.

| Provider | Type | Model id | Notes |
|---|---|---|---|
| **[Novita AI](https://novita.ai/models/model-detail/deepseek-deepseek-ocr-2)** ⭐ | hosted serverless | `deepseek/deepseek-ocr-2` | Best-documented; OpenAI-compatible, image+text in, text out, 8K context. |
| [Siray.ai](https://blog.siray.ai/deepseek-ocr-2/) | hosted unified API | DeepSeek OCR 2 | Confirmed live on launch blog; exact model id requires console login. |
| [JieKou.AI / 接口AI](https://jiekou.ai/models/model-detail/deepseek-deepseek-ocr-2) | domestic aggregator | `deepseek/deepseek-ocr-2` | Fast for quick tests from mainland China. Verify SLA / pricing yourself. |
| [302.AI](https://302.ai/product/detail/ppio-deepseek-deepseek-ocr-2) | aggregator | `deepseek/deepseek-ocr-2` | Verify model is still live in the console before relying on it. |
| [Hugging Face Inference Endpoints](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2) | DIY | `deepseek-ai/DeepSeek-OCR-2` | Spin up a dedicated GPU endpoint from the HF model page. |
| [vLLM / SGLang self-host](https://docs.vllm.ai/projects/recipes/en/latest/DeepSeek/DeepSeek-OCR-2.html) | self-deploy | `deepseek-ai/DeepSeek-OCR-2` | What `Recommended setup` above does. Best for privacy + bulk. |
| [ModelScope 魔搭 + Aliyun FC](https://modelscope.cn/models/deepseek-ai/DeepSeek-OCR-2) | self-deploy on Aliyun | `deepseek-ai/DeepSeek-OCR-2` | Deploy as a Function Compute service or studio. |

### Quick swap

Once you have an endpoint URL + key from any of the above, edit `.env`:

```dotenv
# Example: Novita AI
OCR_API_BASE_URL=https://api.novita.ai/openai/v1   # check provider docs for exact URL
OCR_API_MODEL=deepseek/deepseek-ocr-2              # use the id the provider shows you
OCR_API_KEY=sk-...
```

Restart the server (`python -m suwayomi_ocr`). Translation backend stays on
DeepSeek-v4-flash unchanged.

### Not currently hosting DeepSeek-OCR-2 (don't waste your time)

- **DeepSeek's own API** (`api.deepseek.com`) — only LLMs (v4-flash, v4-pro, chat, reasoner); no OCR-2 endpoint.
- **DeepInfra** — `deepseek-ai/DeepSeek-OCR` (the previous-gen v1, marked for deprecation), **not OCR-2**.
- **Google Vertex AI** — `deepseek-ocr-maas` (v1 via MaaS), **not OCR-2**.
- **Aliyun Bailian (百炼)** — only DeepSeek LLMs (chat/reasoner). No OCR-2 one-click endpoint. For Aliyun, use ModelScope + Function Compute instead.

---

## Quick choice

| If you… | Use |
|---|---|
| are developing / hacking on the server | **Bare metal** — fastest reload loop |
| want a one-command deploy on a Linux box | **Docker Compose** |
| run a fleet / Kubernetes | **Docker** image directly |

All three modes are functionally identical. The Docker image is 250 MB; bare-metal install ≈ 80 MB.

---

## Option A — Bare metal (venv)

```bash
git clone <your-fork>
cd SuwayomiOCR
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env — at minimum set TRANSLATION_API_KEY
$EDITOR .env

python -m suwayomi_ocr
# → listens on 0.0.0.0:12233
```

Requires **Python 3.11+** (uses `str | None` unions, etc.).

The OCR backend (vLLM serving DeepSeek-OCR-2 by default) is **not** managed by
this repo. See [Swapping the OCR backend](#swapping-the-ocr-backend) for how
to point at a local vLLM you have running, or at a cloud vision LLM.

---

## Option B — Docker (single image)

### Build

```bash
docker build -t suwayomi-ocr:latest .
```

### Run with host networking (Linux, local OCR backend)

This is the simplest setup if your OCR backend (e.g. local vLLM) is on the
same machine. `network_mode=host` lets the container reach `127.0.0.1:19260`
directly.

```bash
docker run -d --name suwayomi-ocr --restart unless-stopped \
  --network host \
  --env-file .env \
  suwayomi-ocr:latest
```

### Run with bridge networking (remote OCR backend, Docker Desktop, etc.)

```bash
docker run -d --name suwayomi-ocr --restart unless-stopped \
  -p 12233:12233 \
  --add-host host.docker.internal:host-gateway \
  --env-file .env \
  suwayomi-ocr:latest
```

If you do this, edit `.env` so the OCR URL is reachable from inside the
container — e.g. `OCR_API_BASE_URL=http://host.docker.internal:19260/v1` if
vLLM runs on the host.

### Verify

```bash
curl -H "X-API-Key: $(grep SERVER_API_KEY .env | cut -d= -f2)" \
     http://127.0.0.1:12233/health
# → {"status":"ok"}
```

---

## Option C — Docker Compose

Edit `.env`, then:

```bash
docker compose up -d
docker compose logs -f suwayomi-ocr
docker compose down
```

The default `docker-compose.yml` uses `network_mode: host`. The file has
commented-out blocks showing how to switch to bridge networking with port
mapping. See [docker-compose.yml](../docker-compose.yml).

---

## Configuration reference

All settings live in `.env` (see [.env.example](../.env.example)). Every value
also works as a regular environment variable when running via Docker.

| Variable | Default | Notes |
|---|---|---|
| `SERVER_API_KEY` | `suwasuwa` | Shared secret SuwayomiGO sends as `X-API-Key`. Change it. |
| `SERVER_HOST` | `0.0.0.0` | Bind address. |
| `SERVER_PORT` | `12233` | Listen port. |
| `OCR_API_BASE_URL` | `http://127.0.0.1:19260/v1` | OpenAI-compatible base URL of the vision LLM. |
| `OCR_API_MODEL` | `deepseek-ai/DeepSeek-OCR-2` | Model name to send. |
| `OCR_API_KEY` | _(empty)_ | Optional bearer token for hosted vision APIs. |
| `OCR_API_TIMEOUT_S` | `15` | HTTP timeout per OCR call. |
| `TRANSLATION_API_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible base URL. |
| `TRANSLATION_API_MODEL` | `deepseek-chat` | Model name. |
| `TRANSLATION_API_KEY` | _(empty)_ | Empty disables AI translation; the server falls back to Google Translate. |
| `TRANSLATION_API_TIMEOUT_S` | `8` | HTTP timeout per translate call. |

---

## Swapping the OCR backend

Any chat-completions endpoint that accepts `image_url` content works.
The server sends a single user message with the image and the prompt
`Free OCR.`, with sampling params `temperature=0`, `repetition_penalty=1.1`,
`frequency_penalty=0.3`.

### Local vLLM serving DeepSeek-OCR-2 (default)

Set up vLLM yourself (this repo does not manage it):

```bash
vllm serve deepseek-ai/DeepSeek-OCR-2 \
  --host 0.0.0.0 --port 19260 \
  --trust-remote-code --max-model-len 8192
```

Then in `.env`:

```
OCR_API_BASE_URL=http://127.0.0.1:19260/v1
OCR_API_MODEL=deepseek-ai/DeepSeek-OCR-2
OCR_API_KEY=
```

### OpenAI GPT-4o (vision)

```
OCR_API_BASE_URL=https://api.openai.com/v1
OCR_API_MODEL=gpt-4o-mini
OCR_API_KEY=sk-...
```

### Qwen-VL via DashScope (OpenAI-compatible)

```
OCR_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OCR_API_MODEL=qwen-vl-max
OCR_API_KEY=sk-...
```

> **Note:** vLLM-specific sampling params (`repetition_penalty`,
> `frequency_penalty`) are sent at the top level of the JSON body. Hosted
> providers like OpenAI will silently ignore unknown fields, so the request
> still succeeds. If your provider rejects them, comment them out in
> [ocr_client.py](../suwayomi_ocr/ocr_client.py).

---

## Swapping the translation backend

The translation pipeline calls a chat-completions endpoint with a manga-aware
system prompt (title + chapter) and the OCR'd Japanese as the user message.
Any OpenAI-compatible API works. If `TRANSLATION_API_KEY` is empty, the
server skips the AI call and uses `deep_translator.GoogleTranslator` instead.

### DeepSeek-Chat (default, cheapest)

See default `.env` values above. ≈ $0.35 / 1000 manga pages.

### OpenAI

```
TRANSLATION_API_BASE_URL=https://api.openai.com/v1
TRANSLATION_API_MODEL=gpt-4o-mini
TRANSLATION_API_KEY=sk-...
```

### Qwen via DashScope

```
TRANSLATION_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
TRANSLATION_API_MODEL=qwen-plus
TRANSLATION_API_KEY=sk-...
```

### Doubao via Volcano Ark

```
TRANSLATION_API_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
TRANSLATION_API_MODEL=doubao-pro-32k
TRANSLATION_API_KEY=...
```

### Disabled (Google fallback only)

```
TRANSLATION_API_KEY=
```

The output will be prefixed `[Google翻译] ` so users see the degradation.

---

## SuwayomiGO client setup

In the SuwayomiGO Android app's OCR settings dialog:

| Field | Value |
|---|---|
| OCR server URL | `http://<your-LAN-ip>:12233` |
| OCR secret key | the value of `SERVER_API_KEY` from your `.env` |

Tap the "Test connection" button — it sends a `GET /health` with the key.

---

## Production tips

- **Reverse proxy with TLS.** Run nginx / Caddy in front and terminate TLS
  there. The server itself is plain HTTP.
- **Restrict access.** Put the server on a LAN-only interface, or behind a
  WireGuard / Tailscale tunnel. The `X-API-Key` header is a weak secret on
  its own; pair it with network-level auth for anything internet-facing.
- **Persist nothing.** The server's state (last OCR / last translation) is
  in-memory. Restarting drops it — that's intentional. No volume needed.
- **Resource sizing.** The container itself is ~80 MB resident. CPU/GPU
  load lives in the upstream OCR backend (vLLM), not here.
- **Logs.** Server logs to stdout. With `docker compose`, capture via
  `docker compose logs -f` or a logging driver.
- **Updates.** Pull, rebuild, recreate: `docker compose pull && docker
  compose up -d --build`.
