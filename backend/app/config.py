import os

from dotenv import load_dotenv

load_dotenv()


def _list(name: str, default: str) -> list[str]:
    return [s.strip() for s in os.getenv(name, default).split(",") if s.strip()]


class Settings:
    def __init__(self) -> None:
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")
        self.openrouter_base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        self.models = _list(
            "OPENROUTER_MODELS",
            "openai/gpt-4o-mini,anthropic/claude-sonnet-4.5,google/gemini-2.5-flash",
        )
        self.default_model = os.getenv("OPENROUTER_DEFAULT_MODEL", self.models[0])
        self.app_url = os.getenv("APP_URL", "http://localhost:3000")
        # "deepgram" streams audio server-side; "browser" accepts transcripts from the Web Speech API.
        self.stt_provider = os.getenv("STT_PROVIDER", "deepgram" if os.getenv("DEEPGRAM_API_KEY") else "browser")
        self.deepgram_api_key = os.getenv("DEEPGRAM_API_KEY", "")
        self.deepgram_model = os.getenv("DEEPGRAM_MODEL", "nova-3")
        self.deepgram_language = os.getenv("DEEPGRAM_LANGUAGE", "en")
        self.github_token = os.getenv("GITHUB_TOKEN", "")
        self.cors_origins = _list("CORS_ORIGINS", "http://localhost:3000")
        self.debounce_ms = int(os.getenv("DEBOUNCE_MS", "700"))
        self.max_provisional_per_utterance = int(os.getenv("MAX_PROVISIONAL_PER_UTTERANCE", "3"))
        self.generations_per_minute = int(os.getenv("GENERATIONS_PER_MINUTE", "20"))
        self.max_upload_mb = int(os.getenv("MAX_UPLOAD_MB", "10"))


settings = Settings()
