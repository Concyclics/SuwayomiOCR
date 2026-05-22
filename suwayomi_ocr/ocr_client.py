import re

import httpx

from .config import settings


class OcrUnavailableError(RuntimeError):
    pass


_OCR_PROMPT = "Free OCR."

_FURIGANA_RE = re.compile(r"[（(][぀-ゟ]+[)）]")
_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n?|```$", re.MULTILINE)
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.MULTILINE)
_MD_LIST_RE = re.compile(r"^[\-\*\+]\s+", re.MULTILINE)


def _trim_repetitions(text: str, max_run: int = 2) -> str:
    """Trim consecutive identical lines. DeepSeek-OCR-2 occasionally degenerates
    into a single-line loop on art-heavy pages; this strips the loop tail."""
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
    text = _CODE_FENCE_RE.sub("", text)
    text = _MD_HEADING_RE.sub("", text)
    text = _MD_LIST_RE.sub("", text)
    text = _FURIGANA_RE.sub("", text)
    text = _trim_repetitions(text)
    text = text.strip()
    if text in {"【無】", "無", ""}:
        return ""
    return text


async def recognize(jpeg_b64: str) -> str:
    url = f"{settings.OCR_API_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.OCR_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OCR_API_KEY}"
    payload = {
        "model": settings.OCR_API_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{jpeg_b64}",
                        },
                    },
                    {"type": "text", "text": _OCR_PROMPT},
                ],
            },
        ],
        "temperature": 0.0,
        "max_tokens": 4096,
        "stream": False,
        # vLLM extensions at top level — combat the repetition-loop
        # degeneration that plagues DeepSeek-OCR-2 without its native
        # NoRepeatNGramLogitsProcessor.
        "repetition_penalty": 1.1,
        "frequency_penalty": 0.3,
    }

    try:
        async with httpx.AsyncClient(timeout=settings.OCR_API_TIMEOUT_S) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise OcrUnavailableError(f"vLLM request failed: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OcrUnavailableError(f"unexpected OCR API response: {data}") from exc

    return _post_process(content or "")
