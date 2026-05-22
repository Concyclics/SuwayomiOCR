<!-- LANG-SWITCH -->
[English](DEPLOY.md) | **中文**

# SuwayomiOCR — 部署指南

本文档涵盖**原生**部署与 **Docker** 部署，并说明如何把 OCR / 翻译后端替换为
任意 OpenAI 兼容的提供商。

- [快速选择](#快速选择)
- [方案 A — 原生（venv）](#方案-a--原生venv)
- [方案 B — Docker（单镜像）](#方案-b--docker单镜像)
- [方案 C — Docker Compose](#方案-c--docker-compose)
- [配置参考](#配置参考)
- [替换 OCR 后端](#替换-ocr-后端)
- [替换翻译后端](#替换翻译后端)
- [SuwayomiGO 客户端设置](#suwayomigo-客户端设置)
- [生产环境建议](#生产环境建议)

---

## 快速选择

| 你的场景 | 建议 |
|---|---|
| 二次开发 / 调试服务端 | **原生** — 重启最快 |
| Linux 单机一键部署 | **Docker Compose** |
| K8s / 多机集群 | 直接用 **Docker** 镜像 |

三种模式功能完全一致。Docker 镜像约 250 MB，原生安装约 80 MB。

---

## 方案 A — 原生（venv）

```bash
git clone <你的-fork>
cd SuwayomiOCR
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env — 至少设置 TRANSLATION_API_KEY
$EDITOR .env

python -m suwayomi_ocr
# → 监听 0.0.0.0:12233
```

需要 **Python 3.11+**（用到了 `str | None` 联合类型等）。

OCR 后端（默认是 vLLM 加载 DeepSeek-OCR-2）**不在**本仓库管理范围内。如何指向本机
vLLM 或云端视觉大模型，参见 [替换 OCR 后端](#替换-ocr-后端) 。

---

## 方案 B — Docker（单镜像）

### 构建

```bash
docker build -t suwayomi-ocr:latest .
```

### Host 网络模式运行（Linux + 本机 OCR 后端）

当 OCR 后端（如本机 vLLM）跑在同一台机器上时最简单。`network_mode=host` 让容器
直接访问 `127.0.0.1:19260`。

```bash
docker run -d --name suwayomi-ocr --restart unless-stopped \
  --network host \
  --env-file .env \
  suwayomi-ocr:latest
```

### Bridge 网络模式运行（远程 OCR 后端 / Docker Desktop）

```bash
docker run -d --name suwayomi-ocr --restart unless-stopped \
  -p 12233:12233 \
  --add-host host.docker.internal:host-gateway \
  --env-file .env \
  suwayomi-ocr:latest
```

如果这么跑，需要修改 `.env` 让 OCR URL 在容器内可达 — 比如本机 vLLM 应填
`OCR_API_BASE_URL=http://host.docker.internal:19260/v1`。

### 验证

```bash
curl -H "X-API-Key: $(grep SERVER_API_KEY .env | cut -d= -f2)" \
     http://127.0.0.1:12233/health
# → {"status":"ok"}
```

---

## 方案 C — Docker Compose

编辑 `.env`，然后：

```bash
docker compose up -d
docker compose logs -f suwayomi-ocr
docker compose down
```

默认 `docker-compose.yml` 用 `network_mode: host`。文件里有注释好的代码块演示如何
切换到 bridge + 端口映射。详见 [docker-compose.yml](../docker-compose.yml)。

---

## 配置参考

所有配置项都在 `.env` 中（参考 [.env.example](../.env.example)）。每一项同时也可以
作为普通环境变量传入 Docker。

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SERVER_API_KEY` | `suwasuwa` | SuwayomiGO 通过 `X-API-Key` 发送的共享密钥。**务必修改**。 |
| `SERVER_HOST` | `0.0.0.0` | 绑定地址。 |
| `SERVER_PORT` | `12233` | 监听端口。 |
| `OCR_API_BASE_URL` | `http://127.0.0.1:19260/v1` | 视觉大模型的 OpenAI 兼容 base URL。 |
| `OCR_API_MODEL` | `deepseek-ai/DeepSeek-OCR-2` | 发送的模型名。 |
| `OCR_API_KEY` | _（空）_ | 可选，发往云端视觉 API 时的 bearer token。 |
| `OCR_API_TIMEOUT_S` | `15` | 单次 OCR 调用超时。 |
| `TRANSLATION_API_BASE_URL` | `https://api.deepseek.com/v1` | 翻译大模型的 OpenAI 兼容 base URL。 |
| `TRANSLATION_API_MODEL` | `deepseek-chat` | 模型名。 |
| `TRANSLATION_API_KEY` | _（空）_ | 空 = 禁用 AI 翻译，回落到 Google 翻译。 |
| `TRANSLATION_API_TIMEOUT_S` | `8` | 单次翻译调用超时。 |

---

## 替换 OCR 后端

任何接受 `image_url` 内容的 chat completions 端点都能用。服务端发送的请求是：
单条 user 消息携带图片，prompt 为 `Free OCR.`，采样参数为 `temperature=0`、
`repetition_penalty=1.1`、`frequency_penalty=0.3`。

### 本机 vLLM 跑 DeepSeek-OCR-2（默认）

自行启动 vLLM（本仓库不管这一步）：

```bash
vllm serve deepseek-ai/DeepSeek-OCR-2 \
  --host 0.0.0.0 --port 19260 \
  --trust-remote-code --max-model-len 8192
```

`.env` 配置：

```
OCR_API_BASE_URL=http://127.0.0.1:19260/v1
OCR_API_MODEL=deepseek-ai/DeepSeek-OCR-2
OCR_API_KEY=
```

### OpenAI GPT-4o（视觉）

```
OCR_API_BASE_URL=https://api.openai.com/v1
OCR_API_MODEL=gpt-4o-mini
OCR_API_KEY=sk-...
```

### Qwen-VL（阿里 DashScope，OpenAI 兼容）

```
OCR_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OCR_API_MODEL=qwen-vl-max
OCR_API_KEY=sk-...
```

> **注意：** vLLM 特有采样参数（`repetition_penalty`、`frequency_penalty`）会被放在
> JSON body 顶层。OpenAI 等云厂商会静默忽略未知字段，请求依然成功。如果你的
> provider 拒绝这些字段，在 [ocr_client.py](../suwayomi_ocr/ocr_client.py) 里注释掉即可。

---

## 替换翻译后端

翻译流程会向 chat completions 端点发起调用，带一个漫画感知的 system prompt
（漫画名 + 话数），把 OCR 得到的日文作为 user 消息发过去。任何 OpenAI 兼容 API
都能用。如果 `TRANSLATION_API_KEY` 为空，服务端跳过 AI 调用，改用
`deep_translator.GoogleTranslator`。

### DeepSeek-Chat（默认，最便宜）

参见上面 `.env` 默认值。约 ¥2.5 / 千页漫画。

### OpenAI

```
TRANSLATION_API_BASE_URL=https://api.openai.com/v1
TRANSLATION_API_MODEL=gpt-4o-mini
TRANSLATION_API_KEY=sk-...
```

### Qwen（阿里 DashScope）

```
TRANSLATION_API_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
TRANSLATION_API_MODEL=qwen-plus
TRANSLATION_API_KEY=sk-...
```

### 豆包（火山方舟）

```
TRANSLATION_API_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
TRANSLATION_API_MODEL=doubao-pro-32k
TRANSLATION_API_KEY=...
```

### 禁用（仅用 Google 兜底）

```
TRANSLATION_API_KEY=
```

输出会带 `[Google翻译] ` 前缀，让用户看到降级。

---

## SuwayomiGO 客户端设置

在 SuwayomiGO Android App 的 OCR 设置对话框里：

| 字段 | 填入 |
|---|---|
| OCR server URL | `http://<你机器的局域网IP>:12233` |
| OCR secret key | `.env` 里的 `SERVER_API_KEY` 值 |

点 "Test connection" 按钮 — 它会带着 key 发 `GET /health`。

---

## 生产环境建议

- **反代 + TLS。** 前面套 nginx / Caddy 终止 TLS。服务端自身只跑 HTTP。
- **限制访问面。** 把服务放在内网 / WireGuard / Tailscale 隧道里。`X-API-Key`
  单独使用比较弱，公网暴露的话务必配合网络层鉴权。
- **不做持久化。** 服务端状态（上一次 OCR / 上一次翻译）只在内存中，重启即丢，
  这是设计如此。不需要挂载 volume。
- **资源占用。** 容器自身常驻约 80 MB。CPU/GPU 负载在上游 OCR 后端（vLLM），
  不在这一层。
- **日志。** 服务端日志输出到 stdout。Docker Compose 下用 `docker compose
  logs -f` 查看，或接入日志驱动。
- **更新。** 拉取、重建、重新部署：`docker compose pull && docker compose up
  -d --build`。
