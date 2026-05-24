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
