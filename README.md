<!-- LANG-SWITCH -->
**English** | [中文](README.zh.md)

# SuwayomiOCR

A drop-in OCR + translation backend for the [SuwayomiGO](../SuwayomiGO) Android
manga client. Routes OCR through a vision-LLM (default: vLLM-hosted
**DeepSeek-OCR-2**) and translation through a chat-LLM (default: **DeepSeek-Chat**),
both swappable via env vars to any OpenAI-compatible provider.

Replaces the unmaintained Manga-OCR-Server while preserving its exact HTTP
contract — your SuwayomiGO app works unchanged.

## Highlights

- **Drop-in compatible** — same endpoints, same `X-API-Key` auth, same port 12233 default.
- **Any vision LLM works** — vLLM, OpenAI GPT-4o, Qwen-VL, Claude, …
- **Any chat LLM works** — DeepSeek, OpenAI, Qwen, Doubao, … with Google Translate fallback.
- **Manga-aware translation prompt** — title + chapter passed to the system message.
- **Eager background translation** — `/get_translation` poll usually hits a warm cache.
- **80 MB resident vs. 6 GB legacy** — no on-device PyTorch / EasyOCR / Manga-OCR transformer.
- **Ships with a benchmark suite** — [BENCHMARKS.md](BENCHMARKS.md) measures BLEU / chrF /
  CharF1 / latency / tokens / USD cost across both translation backends.

## Architecture

```
SuwayomiGO (Android)
       │  POST /ocr {image, x, y, mangaName}      X-API-Key
       │  GET  /get_translation                    X-API-Key
       │  GET  /health                             X-API-Key
       ▼
SuwayomiOCR (FastAPI, port 12233)
       │
       ├─► OCR API   ── any OpenAI-compatible vision LLM
       │              (default: local vLLM @ :19260 serving DeepSeek-OCR-2)
       │              → returns Japanese text
       │
       ├─► Janome + manga_dict.db (SQLite, 38 MB Yomitan 明镜日汉双解)
       │              → tokenized words [{s,b,p,r,d}, …]
       │
       └─► Translation API ── any OpenAI-compatible chat LLM
                  ↓ on failure       (default: api.deepseek.com)
              deep_translator / GoogleTranslator
```

## HTTP API

Defined by [SuwayomiGO's MangaOcrManager.kt](../SuwayomiGO/app/src/main/java/com/suwayomi/go/MangaOcrManager.kt):

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/health` | GET | — | `{"status":"ok"}` |
| `/ocr` | POST | `{"image":<b64_jpeg>, "x":int, "y":int, "mangaName":str}` | `{"status":"success","text":<jp>,"words":[…],"translation":""}` |
| `/get_translation` | GET | — | `{"translation":<zh>}` — most recent OCR result |

All endpoints require `X-API-Key: <SERVER_API_KEY>`.

The `/ocr` endpoint schedules a background translation task before returning,
so the `/get_translation` poll a moment later usually hits a warm cache.

## Quick start

```bash
git clone <this-repo>
cd SuwayomiOCR
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env — set TRANSLATION_API_KEY at minimum
python server.py
```

Then in the SuwayomiGO Android app, set OCR server URL to
`http://<your-LAN-ip>:12233` and OCR secret key to your `SERVER_API_KEY`.

For Docker / Docker Compose deployment and swapping OCR/translation backends,
see **[DEPLOY.md](DEPLOY.md)**.

## Benchmarks

A full evaluation across 132 manga pages comparing **DeepSeek-Chat** vs
**Google Translate**, with BLEU/chrF/CharF1 metrics, token usage, and USD cost
estimates, lives in **[BENCHMARKS.md](BENCHMARKS.md)**. Reproduce with:

```bash
# Point at your own paired dataset (JP raw / ZH reference scans):
export BENCHMARK_RAW_DIR=/path/to/raw_jp
export BENCHMARK_REF_DIR=/path/to/ref_zh
python scripts/benchmark.py gather --manga-name "MyManga:Chapter 1"
python scripts/benchmark.py score     # compute metrics, rewrite BENCHMARKS.md
```

Headline (132 pages, this corpus): DeepSeek-Chat edges Google on BLEU/chrF and
qualitatively wins on long-form prose; Google has occasional outright
translation errors on context-sensitive terms. Cost via DeepSeek ≈ $0.35 per
1000 pages.

## Repo layout

```
SuwayomiOCR/
├── server.py                FastAPI app, routes, auth, lifespan
├── ocr_client.py            vision-LLM OCR call + post-processing
├── translation_client.py    chat-LLM translation + Google fallback
├── tokenizer.py             Janome morphological analyzer + dict lookup
├── dict_engine.py           SQLite dict reader
├── state.py                 last-OCR / last-translation cache
├── config.py                pydantic-settings .env loader
├── manga_dict.db            Yomitan 明镜日汉双解 (~38 MB)
├── Dockerfile               production image
├── docker-compose.yml       single-service compose stack
├── .env.example             every env var with comments
├── README.md (en)           README.zh.md (zh)
├── DEPLOY.md (en)           DEPLOY.zh.md (zh)
├── BENCHMARKS.md (en)       BENCHMARKS.zh.md (zh)
└── scripts/
    ├── eval.py              quick visual eyeball across N pages
    └── benchmark.py         full BLEU/chrF/cost report generator
```

## How it compares to legacy Manga-OCR-Server

| | Legacy Manga-OCR-Server | SuwayomiOCR |
|---|---|---|
| OCR model | local `manga-ocr` transformer + EasyOCR detect | any OpenAI-compatible vision LLM |
| Translation | OpenAI-compat + Google fallback | OpenAI-compat + Google fallback (configurable provider) |
| GPU deps on this server | torch, easyocr, transformers (~6 GB) | none (~80 MB) |
| Smart bubble crop | EasyOCR + OpenCV heuristics | dropped — prompt-driven, simpler |
| Japanese tokenizer | Janome | Janome (same) |
| Dictionary DB | `manga_dict.db` | `manga_dict.db` (same, copied) |
| Wire contract | `/ocr`, `/get_translation`, `/health`, `X-API-Key` | identical |
| Default port | 12233 | 12233 |

## License

MIT.

## Acknowledgments

- The legacy [Manga-OCR-Server](../Manga-OCR-Server) for the wire contract and
  `manga_dict.db`.
- [kha-white/manga-ocr](https://github.com/kha-white/manga-ocr) and
  [Janome](https://github.com/mocobeta/janome) for the linguistic stack the
  legacy server built on.
- [DeepSeek-OCR-2](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2) and
  [vLLM](https://github.com/vllm-project/vllm) for the OCR backbone.
