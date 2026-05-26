import json
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    APP_NAME: str
    APP_ENV: str
    APP_DEBUG: bool
    SQL_ECHO: bool = False

    # Server
    HOST: str
    PORT: int

    # Database
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    DATABASE_URL: str
    DATABASE_URL_SYNC: str

    # Redis
    REDIS_PORT: int
    REDIS_URL: str
    REDIS_PASSWORD: str

    # AI model services
    AI_LLM_PROVIDER: str = "http"
    AI_LLM_API_KEY: str = ""
    AI_LLM_BASE_URL: str = "http://127.0.0.1:8003"
    AI_LLM_MODEL: str = "qwen2.5-0.5b-local"
    AI_INTENT_JUDGE_MODEL: str = ""
    AI_GENERAL_REPLY_MODEL: str = ""
    AI_LLM_TIMEOUT_SECONDS: float = 30.0
    AI_LLM_MAX_TOKENS: int = 128
    AI_INTENT_JUDGE_MAX_TOKENS: int = 64
    AI_GENERAL_REPLY_MAX_TOKENS: int = 128
    AI_INTENT_JUDGE_TEMPERATURE: float = 0.0
    AI_GENERAL_REPLY_TEMPERATURE: float = 0.2
    AI_EMBEDDING_ENABLED: bool = True
    AI_EMBEDDING_BASE_URL: str = "http://127.0.0.1:8001"
    AI_EMBEDDING_TIMEOUT_SECONDS: float = 5.0

    # Security
    SECRET_KEY: str
    JWT_ALGORITHM: str
    JWT_EXPIRE_MINUTES: int

    # CORS: store as a JSON array string in .env.
    CORS_ORIGINS: list[str]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        """解析 .env 中的 JSON 数组字符串为 list[str]。"""
        if isinstance(value, list):
            return value
        return json.loads(value)


settings = Settings()
