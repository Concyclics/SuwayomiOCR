import asyncio
import re
import time

from openai import AsyncOpenAI

from .config import settings
from .provider_compat import disable_thinking_extra

_THINK_RE = re.compile(r"<think>.*?</think>\s*|</?think>\s*", re.DOTALL | re.IGNORECASE)

_ai_client: AsyncOpenAI | None = None
if settings.TRANSLATION_API_KEY and settings.TRANSLATION_API_KEY != "sk-REPLACE-ME":
    _ai_client = AsyncOpenAI(
        api_key=settings.TRANSLATION_API_KEY,
        base_url=settings.TRANSLATION_API_BASE_URL,
        timeout=settings.TRANSLATION_API_TIMEOUT_S,
    )
    print(f"[*] translation API client initialized (model={settings.TRANSLATION_API_MODEL})")
else:
    print("[!] TRANSLATION_API_KEY missing — translation will use Google fallback only")


def _build_system_prompt(manga_name: str) -> str:
    if ":" in manga_name:
        manga, episode = manga_name.rsplit(":", 1)
    else:
        manga, episode = "日本漫画", "某一话"

    return (
        f"你是一位精通多门语言的日本漫画翻译专家，正在阅读《{manga}》的{episode}。 \n"
        "你的任务是处理来自 OCR 识别的原文，并完成以下三步：\n"
        "1. **文本校对**：判断识别结果中是否存在因笔画密集导致的错别字，请结合语境将其修正"
        "（例如将错误的形近字还原为正确的词汇）。\n"
        "2. **逻辑断句**：判断因漫画排版导致的非正常连字，并进行逻辑断行或增加标点，"
        "还原角色真实的说话节奏。\n"
        "3. **地道翻译**：基于修正后的原文，结合该作品在此阶段的剧情背景和角色身份进行翻译。\n\n"
        "请翻译成地道、流畅的中文。直接返回译文。"
    )


async def _translate_ai(text: str, manga_name: str) -> str:
    if _ai_client is None:
        raise RuntimeError("translation API client not configured")

    system_content = _build_system_prompt(manga_name)
    start = time.time()
    response = await _ai_client.chat.completions.create(
        model=settings.TRANSLATION_API_MODEL,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": text},
        ],
        temperature=0.3,
        max_tokens=512,
        stream=False,
        # Disable thinking across every known provider (see provider_compat).
        extra_body=disable_thinking_extra("TRANSLATION_EXTRA_BODY"),
    )
    print(f"[ai-translate] {time.time() - start:.2f}s")
    result = (response.choices[0].message.content or "").strip()
    return _THINK_RE.sub("", result).strip()


_GOOGLE_MAX_CHARS = 4500  # GoogleTranslator rejects much longer single calls.


def _translate_google_sync(text: str) -> str:
    from deep_translator import GoogleTranslator

    if len(text) > _GOOGLE_MAX_CHARS:
        text = text[:_GOOGLE_MAX_CHARS]
    return GoogleTranslator(source="ja", target="zh-CN").translate(text)


async def _translate_google(text: str) -> str:
    start = time.time()
    result = await asyncio.to_thread(_translate_google_sync, text)
    print(f"[google] {time.time() - start:.2f}s")
    return f"[Google翻译] {result}"


async def translate(text: str, manga_name: str) -> str:
    if not text.strip():
        return ""

    if _ai_client is not None:
        try:
            return await _translate_ai(text, manga_name)
        except Exception as exc:
            print(f"[ai-translate] failed: {exc}, falling back to Google")

    try:
        return await _translate_google(text)
    except Exception as exc:
        print(f"[google] failed: {exc}")
        return "调用翻译失败，请检查网络或TRANSLATION_API配置"
