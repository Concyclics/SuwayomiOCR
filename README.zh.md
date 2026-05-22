<!-- LANG-SWITCH -->
[English](README.md) | **中文**

# SuwayomiOCR

为 [SuwayomiGO](../SuwayomiGO) Android 漫画客户端提供 OCR + 翻译后端的可直接接入实现。
OCR 走视觉大模型（默认：vLLM 部署的 **DeepSeek-OCR-2**），翻译走聊天大模型（默认：
**DeepSeek-Chat**），通过环境变量两者都可以替换为任意 OpenAI 兼容的提供商。

无缝替换已经停止维护的 Manga-OCR-Server，保留完全相同的 HTTP 协议 — SuwayomiGO
不需要任何改动。

## 主要特点

- **协议兼容** — 端点、`X-API-Key` 鉴权、默认 12233 端口与旧版完全一致。
- **任意视觉大模型** — vLLM、OpenAI GPT-4o、Qwen-VL、Claude 等等。
- **任意聊天大模型** — DeepSeek、OpenAI、Qwen、豆包等等，附带 Google Translate 兜底。
- **漫画感知翻译 prompt** — 漫画名 + 话数会进 system message。
- **后台预翻译** — `/get_translation` 轮询时多半已经能命中缓存。
- **80 MB 常驻 vs 旧版 6 GB** — 不再需要本机 PyTorch / EasyOCR / Manga-OCR 模型权重。
- **自带 benchmark 套件** — [BENCHMARKS.zh.md](BENCHMARKS.zh.md) 衡量两种翻译后端的
  BLEU / chrF / CharF1 / 延迟 / token 用量 / 美元成本。

## 架构

```
SuwayomiGO (Android)
       │  POST /ocr {image, x, y, mangaName}      X-API-Key
       │  GET  /get_translation                    X-API-Key
       │  GET  /health                             X-API-Key
       ▼
SuwayomiOCR (FastAPI, 12233 端口)
       │
       ├─► OCR API   ── 任意 OpenAI 兼容视觉大模型
       │              （默认：本机 vLLM @ :19260 加载 DeepSeek-OCR-2）
       │              → 返回日文
       │
       ├─► Janome + manga_dict.db (SQLite, 38 MB 明镜日汉双解)
       │              → 分词结果 [{s,b,p,r,d}, …]
       │
       └─► 翻译 API ── 任意 OpenAI 兼容聊天大模型
                  ↓ 失败时              （默认：api.deepseek.com）
              deep_translator / GoogleTranslator
```

## HTTP API

协议由 [SuwayomiGO 的 MangaOcrManager.kt](../SuwayomiGO/app/src/main/java/com/suwayomi/go/MangaOcrManager.kt)
定义：

| 端点 | 方法 | 请求体 | 返回 |
|---|---|---|---|
| `/health` | GET | — | `{"status":"ok"}` |
| `/ocr` | POST | `{"image":<b64_jpeg>, "x":int, "y":int, "mangaName":str}` | `{"status":"success","text":<jp>,"words":[…],"translation":""}` |
| `/get_translation` | GET | — | `{"translation":<zh>}` — 上一次 OCR 结果的翻译 |

所有端点都需要 `X-API-Key: <SERVER_API_KEY>` 头。

`/ocr` 返回前会启动一个后台翻译任务，所以稍后轮询 `/get_translation` 多半能命中缓存。

## 快速开始

```bash
git clone <本仓库>
cd SuwayomiOCR
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env — 至少要设置 TRANSLATION_API_KEY
python server.py
```

然后在 SuwayomiGO Android App 里把 OCR 服务器 URL 设为
`http://<你机器的局域网IP>:12233`，OCR 密钥设为你的 `SERVER_API_KEY`。

Docker / Docker Compose 部署，以及如何替换 OCR / 翻译后端，
请看 **[DEPLOY.zh.md](DEPLOY.zh.md)**。

## Benchmark 实验

跨 132 页真实漫画对比 **DeepSeek-Chat** 与 **Google Translate** 的完整实验
（BLEU/chrF/CharF1 指标、token 用量、美元成本估算）在
**[BENCHMARKS.zh.md](BENCHMARKS.zh.md)** 。复现：

```bash
# 指向自己的配对数据集（日文生肉 / 中文熟肉扫描）：
export BENCHMARK_RAW_DIR=/path/to/raw_jp
export BENCHMARK_REF_DIR=/path/to/ref_zh
python scripts/benchmark.py gather --manga-name "我的漫画:第1话"
python scripts/benchmark.py score     # 计算指标，重新生成 BENCHMARKS
```

核心结论（本数据集 132 页）：DeepSeek-Chat 在 BLEU/chrF 上小幅领先 Google，长文本
质感上明显胜出；Google 在某些上下文敏感词上会出现完全错译。DeepSeek 成本约
$0.35 / 千页。

## 仓库结构

```
SuwayomiOCR/
├── server.py                FastAPI app、路由、鉴权、lifespan
├── ocr_client.py            视觉大模型 OCR 调用 + 后处理
├── translation_client.py    聊天大模型翻译 + Google 兜底
├── tokenizer.py             Janome 分词 + 词典查询
├── dict_engine.py           SQLite 词典读取器
├── state.py                 上一次 OCR / 上一次翻译缓存
├── config.py                pydantic-settings .env 加载
├── manga_dict.db            明镜日汉双解词典 (~38 MB)
├── Dockerfile               生产镜像
├── docker-compose.yml       单服务 compose 编排
├── .env.example             所有环境变量带注释
├── README.md (en)           README.zh.md (zh)
├── DEPLOY.md (en)           DEPLOY.zh.md (zh)
├── BENCHMARKS.md (en)       BENCHMARKS.zh.md (zh)
└── scripts/
    ├── eval.py              快速过几页眼观结果
    └── benchmark.py         完整 BLEU/chrF/成本报告生成器
```

## 与旧版 Manga-OCR-Server 对比

| | 旧 Manga-OCR-Server | SuwayomiOCR |
|---|---|---|
| OCR 模型 | 本地 `manga-ocr` transformer + EasyOCR 检测 | 任意 OpenAI 兼容视觉大模型 |
| 翻译 | OpenAI 兼容 + Google 兜底 | OpenAI 兼容 + Google 兜底（可配置 provider） |
| 服务端 GPU 依赖 | torch、easyocr、transformers（~6 GB） | 无（~80 MB） |
| 智能气泡切图 | EasyOCR + OpenCV 启发式 | 移除 — 改为 prompt 驱动 |
| 日文分词 | Janome | Janome（相同） |
| 词典数据库 | `manga_dict.db` | `manga_dict.db`（相同，已复制） |
| HTTP 协议 | `/ocr`、`/get_translation`、`/health`、`X-API-Key` | 完全一致 |
| 默认端口 | 12233 | 12233 |

## 协议

MIT。

## 致谢

- 旧版 [Manga-OCR-Server](../Manga-OCR-Server) — 提供了 HTTP 协议和 `manga_dict.db`。
- [kha-white/manga-ocr](https://github.com/kha-white/manga-ocr) 和
  [Janome](https://github.com/mocobeta/janome) — 旧版用到的语言学组件。
- [DeepSeek-OCR-2](https://huggingface.co/deepseek-ai/DeepSeek-OCR-2) 和
  [vLLM](https://github.com/vllm-project/vllm) — OCR 后端。
