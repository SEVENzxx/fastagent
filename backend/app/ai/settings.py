"""AI 应用层魔法值常量集中管理。

所有超时、限制、默认值必须定义在此，禁止散落在 Handler/Skill/Service 中。
"""

from __future__ import annotations

# ── 上下文限制 ──
MAX_RECENT_PRODUCTS: int = 10          # 最近浏览商品保留数
PRODUCT_CANDIDATE_LIMIT: int = 5       # 商品多候选最大数
DEFAULT_PAGE_SIZE: int = 5             # 商品列表翻页默认每页条数
PRODUCT_CLARIFY_LIMIT: int = 5         # 商品澄清追问最大轮次
RECENT_ORDERS_LIMIT: int = 10          # 最近订单列表长度上限
BATCH_GET_PRODUCTS_LIMIT: int = 10     # 批量查询商品 ID 上限
LAST_KNOWLEDGE_REFS_MAX: int = 5       # last_knowledge_refs 保留条数上限

# ── 超时（秒）──
LLM_TIMEOUT_SECONDS: int = 30          # LLM 调用超时
DB_TIMEOUT_SECONDS: int = 5            # 数据库查询超时
REDIS_TIMEOUT_SECONDS: int = 2         # Redis 读写超时

# ── LLM 限制 ──
LLM_ENTITY_EXTRACT_MAX_TOKENS: int = 500  # 实体抽取 LLM 最大 token
PRODUCT_KNOWLEDGE_TOP_K: int = 5          # 商品知识检索 top_k
POLICY_KNOWLEDGE_TOP_K: int = 5           # 政策知识检索 top_k

# ── Pending ──
PENDING_TTL_SECONDS: int = 1800        # Pending 默认 TTL（30 分钟）
PENDING_MAX_ATTEMPTS: int = 3          # Pending 最大追问轮次
GRAPH_PENDING_TTL_SECONDS: int = 7200  # 图 Pending TTL（2 小时）
IDEMPOTENCY_TTL_ORDER: int = 86400     # 订单幂等 key TTL（24 小时）
IDEMPOTENCY_TTL_AFTERSALES: int = 604800  # 售后幂等 key TTL（7 天）

# ── 场景配置 ──
HIGH_CONFIDENCE_SCORE: float = 0.85    # 高置信意图阈值
HIGH_CONFIDENCE_GAP: float = 0.15      # 高置信候选差距

# ── Knowledge ──
KNOWLEDGE_DEIXIS_KEYWORDS: frozenset = frozenset({"这个", "该", "此", "刚刚", "刚才", "该政策", "该优惠"})
KNOWLEDGE_SHORT_CONTENT_TOKEN_LIMIT: int = 300
