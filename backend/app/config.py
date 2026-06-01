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
    LOG_LEVEL: str = ""
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
    # BAAI/bge-small-zh-v1.5 的标准输出维度为 512。该值必须与 embedding
    # 服务真实输出和 Qdrant collection 配置一致，否则所有向量读写都会失败。
    AI_EMBEDDING_DIMENSION: int = 512

    # Qdrant vector database
    QDRANT_ENABLED: bool = True
    QDRANT_URL: str = "http://127.0.0.1:6333"
    QDRANT_API_KEY: str = ""
    QDRANT_TIMEOUT_SECONDS: float = 5.0
    QDRANT_DISTANCE: str = "Cosine"
    QDRANT_COLLECTION_INTENT_SAMPLES: str = "fastagent_intent_samples"
    QDRANT_COLLECTION_KNOWLEDGE_CHUNKS: str = "fastagent_knowledge_chunks"
    QDRANT_COLLECTION_QA_PAIRS: str = "fastagent_qa_pairs"
    QDRANT_COLLECTION_PRODUCTS: str = "fastagent_products"
    QDRANT_COLLECTION_MARKETING_DOCS: str = "fastagent_marketing_documents"
    QDRANT_COLLECTION_IMAGES: str = "fastagent_images"

    # Agent runtime
    AI_AGENT_ENABLED: bool = True
    AI_AGENT_MODEL: str = ""
    AI_AGENT_MAX_TOKENS: int = 512
    AI_AGENT_TEMPERATURE: float = 0.2
    AI_AGENT_MAX_TOOL_CALLS: int = 3
    AI_AGENT_TIMEOUT_SECONDS: float = 30.0
    AI_AGENT_RECENT_MESSAGE_LIMIT: int = 20
    AI_AGENT_ENABLE_HITL: bool = False
    AI_AGENT_ENABLE_MCP_STUBS: bool = True

    # RAG / Knowledge Base
    AI_RERANKER_PROVIDER: str = "http"
    AI_RERANKER_BASE_URL: str = "http://8.160.180.22:8002/rerank"
    AI_RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    AI_RERANKER_ENABLED: bool = True
    AI_RERANKER_TIMEOUT_SECONDS: float = 10.0
    AI_KNOWLEDGE_TOP_K: int = 20
    AI_KNOWLEDGE_MIN_SCORE: float = 0.7
    AI_KNOWLEDGE_RERANK_TOP_K: int = 5
    AI_KNOWLEDGE_CHUNK_SIZE: int = 500
    AI_KNOWLEDGE_CHUNK_OVERLAP: int = 100
    AI_KNOWLEDGE_MIN_CHUNK_SIZE: int = 100
    AI_KNOWLEDGE_BATCH_SIZE: int = 32
    AI_KNOWLEDGE_QA_MIN_SCORE: float = 0.85
    AI_KNOWLEDGE_QA_TOP_K: int = 3

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
