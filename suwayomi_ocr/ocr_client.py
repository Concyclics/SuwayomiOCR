import re

import httpx

from .config import settings


class OcrUnavailableError(RuntimeError):
    pass


# DeepSeek-OCR-2 is a specialised OCR model that expects a bare one-word
# prompt; all other vision LLMs (Qwen-VL, GPT-4o, Claude …) work better
# with a descriptive instruction.
_PROMPT_DEEPSEEK_OCR = "Free OCR."
_PROMPT_GENERIC = (
    "Extract all Japanese text from this image exactly as written. "
    "Output ONLY the recognized text. Preserve line breaks as \\n. "
    "No commentary, no markdown, no code fences. "
    "If no Japanese text is visible, output exactly: 【無】"
)

_FURIGANA_RE = re.compile(r"[（(][぀-ゟ]+[)）]")
_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|```$", re.MULTILINE)
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_LIST_RE = re.compile(r"^[\-\*\+]\s+", re.MULTILINE)
# Strip leaked thinking tags (Qwen3 occasionally emits </think> even with
# enable_thinking=False, or the full <think>…</think> block).
_THINK_RE = re.compile(r"<think>.*?</think>\s*|</?think>\s*", re.DOTALL | re.IGNORECASE)


def _trim_repetitions(text: str, max_run: int = 2) -> str:
    out: list[str] = []
    prev: str | None = None
    run = 0
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and stripped == prev:
            run += 1
            if run >= max_run:
                continue
        else:
            run = 0
            prev = stripped
        out.append(line)
    return "\n".join(out)


def _post_process(raw: str) -> str:
    text = raw.strip()
    text = _THINK_RE.sub("", text)
    text = _CODE_FENCE_RE.sub("", text)
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_LIST_RE.sub("", text)
    text = _FURIGANA_RE.sub("", text)
    text = _trim_repetitions(text)
    text = text.strip()
    if text in {"【無】", "無", ""}:
        return ""
    return text


def _is_deepseek_ocr(model: str) -> bool:
    return "deepseek-ocr" in model.lower()


async def recognize(jpeg_b64: str) -> str:
    model = settings.OCR_API_MODEL
    use_deepseek = _is_deepseek_ocr(model)

    prompt = _PROMPT_DEEPSEEK_OCR if use_deepseek else _PROMPT_GENERIC

    url = f"{settings.OCR_API_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.OCR_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OCR_API_KEY}"

    payload: dict = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{jpeg_b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            },
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
        "stream": False,
        # Disable chain-of-thought for thinking models (SGLang / Qwen3).
        # Cloud providers and vLLM silently ignore unknown top-level fields.
        "chat_template_kwargs": {"enable_thinking": False},
    }

    if use_deepseek:
        # vLLM-specific params that suppress DeepSeek-OCR-2 repetition loops.
        payload["repetition_penalty"] = 1.1
        payload["frequency_penalty"] = 0.3

    try:
        async with httpx.AsyncClient(timeout=settings.OCR_API_TIMEOUT_S) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise OcrUnavailableError(f"OCR request failed: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OcrUnavailableError(f"unexpected OCR API response: {data}") from exc

    return _post_process(content or "")
