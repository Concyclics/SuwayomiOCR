<!-- LANG-SWITCH -->
**English** | [中文](DEPLOY.zh.md)

# SuwayomiOCR — Deployment Guide

This document covers both **bare-metal** and **Docker** deployment, and how
to swap the OCR / translation backends to any OpenAI-compatible provider.

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
