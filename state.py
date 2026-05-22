import asyncio

last_ocr_text: str = ""
last_manga_name: str = "General"
last_translation: str | None = None
translation_task: asyncio.Task | None = None
lock = asyncio.Lock()
