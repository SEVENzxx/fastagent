"""业务领域常量：商品、知识、订单。"""

# ── 商品 ──
MAX_RECENT_PRODUCTS: int = 10              # 最近浏览商品保留数
PRODUCT_CANDIDATE_LIMIT: int = 5           # 商品多候选最大数
DEFAULT_PAGE_SIZE: int = 5                 # 商品列表翻页默认每页条数
PRODUCT_CLARIFY_LIMIT: int = 5             # 商品澄清追问最大轮次
BATCH_GET_PRODUCTS_LIMIT: int = 10         # 批量查询商品 ID 上限
PRODUCT_KNOWLEDGE_TOP_K: int = 5           # 商品知识检索 top_k

# ── 知识 ──
LAST_KNOWLEDGE_REFS_MAX: int = 5           # last_knowledge_refs 保留条数上限
POLICY_KNOWLEDGE_TOP_K: int = 5            # 政策知识检索 top_k
KNOWLEDGE_SHORT_CONTENT_TOKEN_LIMIT: int = 300   # 知识分块短内容 token 阈值
KNOWLEDGE_DEIXIS_KEYWORDS: frozenset = frozenset({"这个", "该", "此", "刚刚", "刚才", "该政策", "该优惠"})

# ── 订单 ──
RECENT_ORDERS_LIMIT: int = 10              # 最近订单列表长度上限
IDEMPOTENCY_TTL_ORDER: int = 86400         # 订单幂等 key TTL（24 小时）
IDEMPOTENCY_TTL_AFTERSALES: int = 604800   # 售后幂等 key TTL（7 天）
