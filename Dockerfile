# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: nothing native required at runtime — pillow ships wheels,
# sqlite3 is stdlib, janome is pure-Python.

# Install Python deps (split layer for cache).
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Copy app package + dictionary DB.
COPY suwayomi_ocr/ ./suwayomi_ocr/
COPY data/manga_dict.db ./data/manga_dict.db

EXPOSE 12233

# Healthcheck — requires SERVER_API_KEY to be passed at run-time.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request,sys; \
req=urllib.request.Request(f'http://127.0.0.1:{os.environ.get(\"SERVER_PORT\",\"12233\")}/health', \
headers={'X-API-Key': os.environ.get('SERVER_API_KEY','')}); \
sys.exit(0 if urllib.request.urlopen(req, timeout=3).status == 200 else 1)" || exit 1

CMD ["python", "-m", "suwayomi_ocr"]
