"""系统配置常量：LLM、Pending、场景识别、Redis 等运行时参数。"""

# ── LLM ──
LLM_ENTITY_EXTRACT_MAX_TOKENS: int = 500         # 实体抽取 LLM 最大 token
PRODUCT_ATTR_EXTRACT_MAX_TOKENS: int = 1024      # 商品属性抽取 max_tokens
SCENE_RECOGNITION_MAX_TOKENS: int = 200          # 场景识别 LLM 判决 max_tokens
SEMANTIC_RECOMMEND_MAX_TOKENS: int = 512         # 语义推荐 LLM max_tokens

# ── Pending ──
GRAPH_PENDING_TTL_SECONDS: int = 7200            # LangGraph Pending TTL（2 小时）

# ── 场景识别 ──
HIGH_CONFIDENCE_SCORE: float = 0.75              # 高置信意图阈值
HIGH_CONFIDENCE_GAP: float = 0.15                # 高置信候选差距

# ── Redis / 缓存 ──
SESSION_TTL: int = 3600                          # SessionContext 过期时间（秒，1 小时）
IDEMPOTENCY_TTL: int = 86400                     # 幂等 key 默认过期时间（秒，24 小时）
TENANT_LLM_CONFIG_CACHE_TTL: int = 86400         # 租户 LLM 配置 Redis 缓存过期时间（秒，24 小时）
TENANT_ATTR_CACHE_TTL: int = 86400               # 租户属性配置 Redis 缓存过期时间（秒，24 小时）
