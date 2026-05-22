import asyncio
import base64
import socket
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import Body, Depends, FastAPI, HTTPException, Security, status
from fastapi.security import APIKeyHeader

import state
from config import settings
from ocr_client import OcrUnavailableError, recognize
from tokenizer import analyze
from translation_client import translate

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str = Security(api_key_header)) -> str:
    if api_key == settings.SERVER_API_KEY:
        return api_key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid API Key. Access Denied.",
    )


async def _ping_ocr_backend() -> None:
    url = f"{settings.OCR_API_BASE_URL.rstrip('/')}/models"
    headers = {}
    if settings.OCR_API_KEY:
        headers["Authorization"] = f"Bearer {settings.OCR_API_KEY}"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                print(f"[*] OCR backend reachable at {settings.OCR_API_BASE_URL}")
                return
            print(f"[!] OCR backend responded {resp.status_code} at {url}")
    except Exception as exc:
        print(f"[!] OCR backend unreachable at {url}: {exc}")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await _ping_ocr_backend()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "127.0.0.1"
    print(f"[*] SuwayomiOCR listening on http://{local_ip}:{settings.SERVER_PORT}")
    yield


app = FastAPI(title="SuwayomiOCR", lifespan=lifespan)


@app.get("/health")
async def health_check(_: str = Depends(verify_api_key)) -> dict:
    return {"status": "ok"}


@app.post("/ocr")
async def perform_ocr(
    payload: dict = Body(...),
    _: str = Depends(verify_api_key),
) -> dict:
    img_b64 = payload.get("image")
    manga_name = payload.get("mangaName", "General")

    if not img_b64:
        return {"status": "error", "message": "No image data"}

    try:
        img_bytes = base64.b64decode(img_b64, validate=False)
    except Exception as exc:
        return {"status": "error", "message": f"invalid base64: {exc}"}

    if len(img_bytes) > MAX_IMAGE_BYTES:
        return {"status": "error", "message": f"image too large ({len(img_bytes)} bytes)"}

    async with state.lock:
        state.last_translation = None
        if state.translation_task is not None and not state.translation_task.done():
            state.translation_task.cancel()
        state.translation_task = None

    try:
        text = await recognize(img_b64)
    except OcrUnavailableError as exc:
        print(f"[ocr] unavailable: {exc}")
        return {
            "status": "error",
            "text": "OCR服务暂时不可用，请检查vLLM后端",
            "words": [],
            "translation": "",
        }

    words = analyze(text)

    async with state.lock:
        state.last_ocr_text = text
        state.last_manga_name = manga_name
        state.last_translation = None
        if text:
            state.translation_task = asyncio.create_task(translate(text, manga_name))
        else:
            state.translation_task = None

    print(f"[ocr] mangaName={manga_name!r} text={text!r}")
    return {
        "status": "success",
        "text": text,
        "words": words,
        "translation": "",
    }


@app.get("/get_translation")
async def get_translation(_: str = Depends(verify_api_key)) -> dict:
    async with state.lock:
        text = state.last_ocr_text
        cached = state.last_translation
        task = state.translation_task

    if not text:
        return {"translation": "未检测到待翻译文字"}

    if cached is not None:
        return {"translation": cached}

    if task is None:
        # No background task scheduled (e.g. /ocr returned empty text but state preserved an older entry)
        result = await translate(text, state.last_manga_name)
    else:
        try:
            result = await asyncio.wait_for(asyncio.shield(task), timeout=10.0)
        except asyncio.TimeoutError:
            return {"translation": "翻译超时，请稍后重试"}
        except Exception as exc:
            print(f"[translate] task failed: {exc}")
            result = "调用翻译失败，请检查网络或DeepSeek配置"

    async with state.lock:
        state.last_translation = result

    print(f"[translate] {text!r} -> {result!r}")
    return {"translation": result}


if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        log_level="info",
    )
