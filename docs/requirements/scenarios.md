# FastAgent 场景需求说明
> 更新日期：2026-07-02  
> 本文档描述当前项目已经注册和实现的对话场景，用于维护场景识别、路由、权限边界和测试用例。代码基准为 `backend/app/ai/scenario/spec.py`、`backend/app/ai/handlers/registry.py`、`backend/app/ai/recognition/pipeline.py` 和各领域 Handler。

---

## 1. 场景体系

当前场景以 `scenario_id` 为业务入口，不再按单一意图名维护。一次用户消息的主流程是：

1. `ContextResolver` 先处理上下文延续，例如商品列表序号、这款/它/那个、适用性追问。
2. `RecognitionPipeline` 执行短确认上下文优先、无上下文歧义词澄清、强规则匹配、向量召回和 LLM 判决。
3. `HandlerRegistry` 根据 `scenario_id` 找到唯一 Handler。
4. Handler 调用受允许的 Skill、知识检索、LangGraph 子图或模板回复。
5. `PolicyGuard` 根据 `ScenarioSpec` 对 Skill、LLM、向量检索、Pending 和风险等级做后置校验。

当前注册场景共 29 个，分为 6 类：

| 类别 | 数量 | Handler |
| --- | ---: | --- |
| 商品 | 9 | `ProductHandler` |
| 订单 | 8 | `OrderHandler` |
| 知识 | 3 | `KnowledgeHandler` |
| 记忆 | 2 | `MemoryHandler` |
| 模板 | 6 | `TemplateHandler` |
| 人工 | 1 | `HumanHandler` |

---

## 2. 场景总表

| scenario_id | Handler | 风险等级 | 主要能力 | 典型输入 |
| --- | --- | --- | --- | --- |
| `product.catalog` | `ProductHandler` | `read_only` | `list_categories` | 你们有什么产品 |
| `product.filter_search` | `ProductHandler` | `read_only` | `search_products`，允许实体抽取 | 预算低一点有什么推荐 |
| `product.semantic_recommend` | `ProductHandler` | `read_only` | `search_products`，允许实体抽取和向量检索 | 根据我的需求推荐一下 |
| `product.sku_query` | `ProductHandler` | `read_only` | `search_by_sku` | 按货号查一下 |
| `product.detail` | `ProductHandler` | `read_only` | `get_detail`、`search_products`、`search_product_knowledge`，允许知识增强回复 | 这个多少钱 |
| `product.compare` | `ProductHandler` | `read_only` | `batch_get_detail`、`get_detail`、`search_products` | 第一款和第二款有什么区别 |
| `product.attribute_query` | `ProductHandler` | `read_only` | `search_products`、`get_detail`、`get_attribute` | 这款有哪些参数 |
| `product.usage` | `ProductHandler` | `read_only` | `get_detail`、`search_product_knowledge`，允许知识增强回复 | 适合跑步吗 |
| `product.pagination_sort` | `ProductHandler` | `read_only` | `batch_get_detail` | 下一页、按价格排序 |
| `order.list` | `OrderHandler` | `read_only` | `manage_order` | 查一下我的订单 |
| `order.filter` | `OrderHandler` | `read_only` | `manage_order` | 未发货的订单有哪些 |
| `order.detail` | `OrderHandler` | `read_only` | `manage_order` | 订单进度怎么样 |
| `order.shipping_status` | `OrderHandler` | `read_only` | `manage_order` | 查物流 |
| `order.create` | `OrderHandler` | `write_confirm` | `manage_order`、`create_order_draft`，允许 Pending | 我要买这个 |
| `order.cancel` | `OrderHandler` | `write_confirm` | `manage_order`、`cancel_order_draft`，允许 Pending | 取消订单 |
| `order.confirm` | `OrderHandler` | `write_confirm` | `confirm_order`，允许 Pending | 确认、没问题 |
| `order.refund` | `OrderHandler` | `write_confirm` | `manage_order`、`create_refund`，允许 Pending | 申请售后 |
| `knowledge.qa` | `KnowledgeHandler` | `read_only` | `search_qa`、`search_knowledge`，允许向量和摘要回复 | 怎么付款 |
| `knowledge.policy` | `KnowledgeHandler` | `read_only` | `search_qa`、`search_knowledge`，允许向量和摘要回复 | 有什么优惠 |
| `knowledge.product_qa` | `KnowledgeHandler` | `read_only` | `search_qa`、`search_knowledge`，允许向量和摘要回复 | 这个保修多久 |
| `memory.save` | `MemoryHandler` | `write_confirm` | `remember_info` | 记住我喜欢黑色 |
| `memory.recall` | `MemoryHandler` | `read_only` | `recall_info` | 我有什么偏好 |
| `template.greeting` | `TemplateHandler` | `read_only` | 模板回复 | 你好、在吗 |
| `template.confirmation` | `TemplateHandler` | `read_only` | 模板回复 | 好的、收到 |
| `template.farewell` | `TemplateHandler` | `read_only` | 模板回复 | 谢谢、再见、没事了 |
| `template.silent` | `TemplateHandler` | `read_only` | 空消息/静默模板 | 空消息 |
| `template.fallback` | `TemplateHandler` | `read_only` | 兜底回复 | 无法识别的问题 |
| `template.clarify` | `TemplateHandler` | `read_only` | 歧义澄清 | 无上下文的“确认/取消” |
| `human.transfer` | `HumanHandler` | `human_required` | 转人工信号、清理 Pending | 转人工、我要投诉 |

---

## 3. 识别与路由规则

### 3.1 上下文优先

`ContextResolver` 在场景识别之前运行，只处理上下文延续：

- 裸序号或“第一个”：如果 `last_visible_products` 存在且文本不包含购买关键词，路由到 `product.detail`。
- 指代词：以“这个/这款/它/那个”等开头，且存在 `last_focus_product_id` 时，路由到 `product.detail` 或 `product.usage`。
- 省略型适用性问题：已有焦点商品且文本包含“适合/用来/用于”时，路由到 `product.usage`。
- 带购买关键词的序号，例如“下单第一款”，不在上下文解析中消费，交给订单场景识别。

### 3.2 识别管线

`RecognitionPipeline` 的当前顺序是：

1. 短确认 + `draft_order_id`：直接识别为 `order.confirm`。
2. 无业务上下文的“确认/取消/算了/不要了”：识别为 `template.clarify`，不触发向量和 LLM。
3. 强规则：转人工、投诉、辱骂、法律威胁、退订、纯确认、感谢、空消息。
4. 向量召回：从平台默认样本和租户样本中召回候选。
5. LLM 判决：高置信候选可短路，歧义场景交给 LLM 精判。
6. 兜底：无法判断时返回 `template.fallback`。

### 3.3 强规则边界

强规则优先级高于向量和 LLM：

- 明确要求人工、投诉、辱骂、法律威胁、账号删除等直接进入 `human.transfer`。
- 空消息进入 `template.silent`。
- 纯确认/收到类短句进入 `template.confirmation`，但如果存在订单草稿，短确认优先进入 `order.confirm`。
- 包含“退款/退货/退钱/怎么退/不想要了”等关键词的消息当前优先进入 `human.transfer`。

因此，`order.refund` 虽然已经有场景规约、Handler 注册和 LangGraph 子图，但常见退款关键词会被强规则优先转人工。只有未被强规则截获且被识别为售后流程的消息，才会进入 `order.refund`。

---

## 4. 商品场景

商品类场景全部由 `ProductHandler` 处理，核心状态写入 `SessionContext`，用于后续序号选择、指代、对比和下单。

| 场景 | 当前行为 | 上下文影响 |
| --- | --- | --- |
| `product.catalog` | 查询商品分类并返回分类列表。 | 记录 `last_intent`。 |
| `product.filter_search` | 通过 `ProductFilterExtractor` 抽取价格、分类、属性等条件，再调用商品搜索。 | 写入 `product_candidates`、`last_visible_products`、`last_product_query`，清理焦点商品。 |
| `product.semantic_recommend` | 用自然语言需求搜索商品，返回候选列表。 | 写入候选列表和最近查询。 |
| `product.sku_query` | 按 SKU 或货号精确查询商品。 | 设置 `last_product_id`、`last_product_name`、`last_focus_product_id`。 |
| `product.detail` | 解析商品引用，支持焦点商品、序号、商品名搜索；命中单商品后查详情。 | 设置焦点商品；多候选时写入候选列表。 |
| `product.compare` | 支持两个序号直接对比，或基于 `compare_base_product_id` 做连续对比。 | 写入 `compare_base_product_id` 和 `compare_product_ids`。 |
| `product.attribute_query` | 查询指定商品全部属性或指定属性。 | 设置焦点商品。 |
| `product.usage` | 基于焦点商品回答适用场景、使用方式、人群等问题。 | 设置或保持焦点商品。 |
| `product.pagination_sort` | 基于已有候选列表翻页或排序。 | 更新候选列表和 `product_page`。 |

维护规则：

- 商品详情、属性、用法问题必须先解析到具体商品；没有焦点或候选时应追问。
- 商品列表类场景要维护 `last_visible_products`，否则序号选择和“下单第一款”无法稳定工作。
- 对比场景至少需要两个明确商品；只有一个商品或无基准商品时应追问。
- `product.pagination_sort` 依赖已有候选列表，不应在没有商品列表时重新发起泛搜索。

---

## 5. 订单场景

订单类场景全部由 `OrderHandler` 处理。查询类走 `manage_order`，写操作走 LangGraph 子图并通过 `PendingState` 恢复。

| 场景 | 当前行为 | Pending |
| --- | --- | --- |
| `order.list` | 查询当前联系人订单列表；无联系人时要求先确认客户身份。 | 不设置 |
| `order.filter` | 按状态或时间筛选订单，例如待付款、未发货、本周。 | 不设置 |
| `order.detail` | 解析订单引用，查询指定订单；无订单引用时回落为订单列表选择。 | 不设置 |
| `order.shipping_status` | 查询物流/发货状态；无订单引用时回落为订单列表选择。 | 不设置 |
| `order.create` | 创建下单图线程，支持焦点商品、序号商品、指代商品；图中断时等待用户补充。 | 允许 |
| `order.cancel` | 创建取消订单图线程，确认取消对象和取消动作。 | 允许 |
| `order.confirm` | 场景规约和注册已存在；当前确认动作主要由订单图 Pending 恢复消费，普通 execute 尚无独立确认分支。 | 允许 |
| `order.refund` | 创建售后/退款图线程。常见退款关键词当前可能先被强规则转人工。 | 允许 |

维护规则：

- 订单查询必须有 `contact_id`，否则只能引导先确认客户身份。
- 短确认词只有在有图 Pending 或明确草稿上下文时才能表达确认语义；当前真正写入确认主要由图恢复路径执行。
- 没有上下文的“确认/取消/不要了”必须走澄清或 PendingGuard，不应直接执行写操作。
- 写操作通过 LangGraph checkpoint 恢复，`PendingState` 只保存图线程和中断信息。
- 重复恢复已完成图时要返回“请勿重复操作”类回复，避免重复提交。

---

## 6. 知识场景

知识类场景由 `KnowledgeHandler` 处理，原则是不编造知识、无 LLM 兜底。当前路径是：

1. 如果是追问且存在 `last_knowledge_refs`，优先在上次引用范围内精准续查。
2. 先查 QA pair，高置信命中直接返回。
3. 再查知识分块，单条短内容直出，多条或长内容用摘要回复。
4. 无命中时返回未查到话术。

| 场景 | 适用范围 |
| --- | --- |
| `knowledge.qa` | 支付方式、发票、通用 FAQ 等。 |
| `knowledge.policy` | 优惠、促销、发货时效、配送政策等。 |
| `knowledge.product_qa` | 与当前焦点商品绑定的保修、安装、清洗、保养、材质等问题。 |

维护规则：

- `knowledge.product_qa` 需要 `last_focus_product_id`；没有焦点商品时应追问具体商品。
- 知识命中后要维护 `last_knowledge_refs`，支持后续“这个还有别的吗”类追问。
- 不能为了回答而绕过知识库生成事实性内容。

---

## 7. 记忆场景

记忆类场景由 `MemoryHandler` 处理，依赖联系人身份。

| 场景 | 当前行为 |
| --- | --- |
| `memory.save` | 调用 `remember_info` 抽取并保存客户偏好、要求、备注等长期记忆。 |
| `memory.recall` | 调用 `recall_info` 查询当前联系人的历史记忆。 |

维护规则：

- 没有 `contact_id` 时不能保存或查询个人记忆。
- 记忆保存是写操作，必须保持在 `ScenarioSpec` 的写权限场景内。
- 记忆场景当前不使用 Pending 恢复。

---

## 8. 模板与人工场景

模板场景由 `TemplateHandler` 统一返回固定话术，并清理 Pending：

- `template.greeting`：问候。
- `template.confirmation`：纯确认、收到。
- `template.farewell`：感谢、告别或结束会话。
- `template.silent`：空消息。
- `template.fallback`：无法识别或无合适场景。
- `template.clarify`：无上下文歧义词澄清。

人工场景由 `HumanHandler` 处理：

- `human.transfer` 返回转人工话术。
- `context_update` 会携带 `requires_human_handoff` 和 `pending_human_approval`。
- Processor 消费该信号后执行会话状态变更、坐席分配和 WebSocket 广播。
- 转人工时会清理当前 Pending。

---

## 9. 风险与权限规则

`ScenarioSpec` 是场景行为边界，维护时必须同步更新场景规约、Handler 注册和样本。

| 风险等级 | 含义 |
| --- | --- |
| `read_only` | 只允许读 Skill；不能调用写 Skill；不能设置 Pending。 |
| `write_confirm` | 允许指定写 Skill；可按场景配置设置 Pending。 |
| `human_required` | 必须走人工处理，不应自动执行业务动作。 |

当前写 Skill 集合包括：

- `create_order_draft`
- `confirm_order`
- `cancel_order_draft`
- `update_order_draft`
- `update_draft_order_quantity`
- `remember_info`

实现注意：`order.refund` 当前允许并调用 `create_refund`，但全局写 Skill 集合尚未把 `create_refund` 列入写操作。继续启用自动售后时，应同步补齐这项权限校验。

维护规则：

- 新增场景必须先定义 `ScenarioSpec`，再注册 Handler。
- Handler 调用的 Skill 必须出现在该场景的 `allowed_skills` 中。
- 如果 Handler 会设置 Pending，必须在 `ScenarioSpec` 中开启 `allow_pending`。
- 如果 Handler 会调用 LLM 或向量检索，必须开启对应允许项。
- `read_only` 场景不能通过任何间接路径触发写 Skill。

---

## 10. 样本维护规则

平台默认样本位于 `backend/app/ai/recognition/examples.py`，租户样本用于补充行业词、商品词和业务表达。维护样本时遵守以下规则：

- 样本标注以 `scenario_id` 为准。
- 常规业务样本应覆盖陈述、疑问、口语、省略、指代和序号表达。
- 高风险写操作样本必须能区分“查询意图”和“执行意图”。
- 短确认、取消、退出类表达必须结合上下文判断，不能只靠样本文本直接触发写操作。
- 人工转接、投诉、辱骂、法律威胁等高优先级表达优先维护在强规则中。
- 新增样本后需要重建或刷新向量索引，并用 Harness 覆盖关键场景。

---

## 11. 回归验证重点

场景相关变更至少覆盖以下验证：

1. 商品列表后回复“第一个”进入 `product.detail`。
2. 商品列表后回复“下单第一款”进入 `order.create`，不能被上下文详情解析截获。
3. 无上下文直接说“确认”进入 `template.clarify`。
4. 有订单图 Pending 时说“确认”应恢复对应图流程，而不是重新识别为普通查询。
5. 空消息进入 `template.silent`。
6. 投诉、辱骂、法律威胁进入 `human.transfer`。
7. 商品适用性追问在有焦点商品时进入 `product.usage`。
8. 知识追问能使用 `last_knowledge_refs` 缩小检索范围。
9. 订单查询无 `contact_id` 时不会泄露订单信息。
10. 写操作场景设置 Pending 后可以恢复，并且完成后不能重复提交。



