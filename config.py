from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Server's own auth — clients send this in `X-API-Key` header.
    SERVER_API_KEY: str = "suwasuwa"

    # Upstream OCR backend — any OpenAI-compatible chat-completions endpoint
    # that accepts image_url content. Defaults to a local vLLM running
    # DeepSeek-OCR-2; swap to GPT-4o, Claude, Qwen-VL, or any hosted vision LLM.
    OCR_API_BASE_URL: str = "http://127.0.0.1:19260/v1"
    OCR_API_MODEL: str = "deepseek-ai/DeepSeek-OCR-2"
    OCR_API_KEY: str = ""           # optional bearer token (vLLM local doesn't need it)
    OCR_API_TIMEOUT_S: float = 15.0

    # Upstream translation backend — any OpenAI-compatible chat-completions
    # endpoint. Defaults to DeepSeek-Chat; swap to OpenAI, Qwen, Doubao, etc.
    # Leave key empty to disable AI translation and use Google fallback only.
    TRANSLATION_API_BASE_URL: str = "https://api.deepseek.com/v1"
    TRANSLATION_API_MODEL: str = "deepseek-chat"
    TRANSLATION_API_KEY: str = ""
    TRANSLATION_API_TIMEOUT_S: float = 8.0

    SERVER_HOST: str = "0.0.0.0"
    SERVER_PORT: int = 12233

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
