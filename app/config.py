import os
from functools import lru_cache

try:
    from pydantic_settings import BaseSettings
except ImportError:
    BaseSettings = None  # type: ignore

_DEFAULT_DATABASE_URL = "mysql+asyncmy://root:password@127.0.0.1:3306/router"
_DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"


if BaseSettings is not None:

    class Settings(BaseSettings):
        openai_api_key: str = ""
        anthropic_api_key: str = ""
        dashscope_api_key: str = ""  # 阿里云 DashScope / 通义千问 Qwen
        database_url: str = _DEFAULT_DATABASE_URL
        redis_url: str = _DEFAULT_REDIS_URL
        host: str = "0.0.0.0"
        port: int = 8000

        class Config:
            env_file = ".env"
            extra = "ignore"
else:

    class Settings:  # type: ignore
        def __init__(self):
            try:
                from dotenv import load_dotenv
                load_dotenv()
            except ImportError:
                pass
            self.openai_api_key = os.environ.get("OPENAI_API_KEY", "")
            self.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            self.dashscope_api_key = os.environ.get("DASHSCOPE_API_KEY", "")
            self.database_url = os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL)
            self.redis_url = os.environ.get("REDIS_URL", _DEFAULT_REDIS_URL)
            self.host = os.environ.get("HOST", "0.0.0.0")
            self.port = int(os.environ.get("PORT", "8000"))


@lru_cache
def get_settings() -> Settings:
    return Settings()
