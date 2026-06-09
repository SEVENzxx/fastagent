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

    # ── 本地 AI 模型（意图精判 + 通用回复兜底） ──
    AI_LLM_PROVIDER: str = "http"
    AI_LLM_API_KEY: str = ""
    AI_LLM_BASE_URL: str = "http://127.0.0.1:8003"
    AI_LLM_MODEL: str = "qwen2.5-0.5b-local"
    AI_LLM_TIMEOUT_SECONDS: float = 30.0
    AI_GENERAL_REPLY_TIMEOUT_SECONDS: float = 5.0
    AI_LLM_MAX_TOKENS: int = 128

    # ── Embedding ──
    AI_EMBEDDING_ENABLED: bool = True
    AI_EMBEDDING_BASE_URL: str = "http://127.0.0.1:8001"
    AI_EMBEDDING_TIMEOUT_SECONDS: float = 5.0
    AI_EMBEDDING_DIMENSION: int = 512  # 必须与 embedding 服务真实输出和 Qdrant collection 一致

    # ── Qdrant ──
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

    # ── Agent 行为控制（非模型参数，模型参数由租户 LLMConfig 接管） ──
    AI_AGENT_ENABLED: bool = True
    AI_AGENT_MAX_TOOL_CALLS: int = 3
    AI_AGENT_TIMEOUT_SECONDS: float = 30.0
    AI_AGENT_RECENT_MESSAGE_LIMIT: int = 20
    AI_AGENT_ENABLE_HITL: bool = False
    AI_AGENT_ENABLE_MCP_STUBS: bool = True
    AI_AGENT_ENABLE_LLM_ARGUMENT_EXTRACTION: bool = False

    # RAG / Knowledge Base
    AI_RERANKER_PROVIDER: str = "http"
    AI_RERANKER_BASE_URL: str = "http://8.160.180.22:8002/rerank"
    AI_RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"
    AI_RERANKER_ENABLED: bool = True
    AI_RERANKER_TIMEOUT_SECONDS: float = 10.0
    AI_KNOWLEDGE_TOP_K: int = 20
    AI_KNOWLEDGE_MIN_SCORE: float = 0.50
    AI_KNOWLEDGE_RERANK_TOP_K: int = 5
    AI_KNOWLEDGE_CHUNK_SIZE: int = 500
    AI_KNOWLEDGE_CHUNK_OVERLAP: int = 100
    AI_KNOWLEDGE_MIN_CHUNK_SIZE: int = 100
    AI_KNOWLEDGE_BATCH_SIZE: int = 32
    AI_KNOWLEDGE_QA_MIN_SCORE: float = 0.85
    AI_KNOWLEDGE_QA_TOP_K: int = 3
    AI_GENERAL_REPLY_RAG_TOP_K: int = 5
    AI_GENERAL_REPLY_RAG_MIN_SCORE: float = 0.50
    AI_PRODUCT_VECTOR_TOP_K: int = 10
    AI_PRODUCT_VECTOR_MIN_SCORE: float = 0.45
    AI_PRODUCT_CONSULT_KNOWLEDGE_TOP_K: int = 5
    AI_PRODUCT_CONSULT_KNOWLEDGE_MIN_SCORE: float = 0.45
    AI_PRODUCT_CONSULT_USE_LLM_WHEN_HAS_CONTEXT: bool = True

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
