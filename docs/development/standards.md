# FastAgent 开发规范

> 更新日期：2026-07-02

本文档定义 FastAgent Agent 模块的开发规则、行为边界和代码审查标准。所有规则以当前代码结构为准，目标是让业务链路可读、可控、可测试。

## 一、基本原则

1. **职责单一**：每个目录、类和函数只承担明确职责，不把识别、抽参、业务执行、回复生成混在一起。
2. **结构化传递**：跨层传参优先使用结构化对象、Pydantic 模型或明确字段，不传递含义不清的 `dict[str, Any]`。
3. **受控调用**：LLM、向量检索、Skill 调用必须走统一入口，确保 `ResourceTrace` 可记录、可断言。
4. **租户隔离**：任何涉及业务数据的查询和写入都必须携带并校验 `tenant_id`。
5. **写操作可确认、可幂等**：创建订单、确认订单、取消订单、售后等写操作必须有确认链路和幂等保护。
6. **失败可降级**：外部服务、LLM、Redis、向量库失败时要有明确降级路径，不能让异常泄漏到用户侧。
7. **文档同步**：修改架构边界、场景行为或测试入口时，同步更新 `docs/` 中对应说明。

## 二、目录职责

| 目录 | 职责 | 行为边界 |
|------|------|----------|
| `entry/` | 消息入口、过滤、合并、防抖、落库推送 | 不做场景识别，不调用 LLM，不处理具体业务 |
| `assistant/` | 主编排、Pending 优先处理、Handler 路由、结果收口 | 不写具体业务逻辑，不直接拼回复文案 |
| `recognition/` | 场景识别，输出 `ScenarioDecision` | 不解析最终业务 ID，不直接查业务数据 |
| `context/` | SessionContext、PendingState 的存取 | 不放业务判断 |
| `components/` | 参数解析、实体解析、合法性校验 | 不执行写操作，不调用 Skill |
| `handlers/` | 单个场景的流程编排 | 不绕过 Gateway 调用 LLM、Vector、Skill |
| `skills/` | 结构化业务能力，负责读写业务数据 | 不接收用户原始文本，不做意图识别 |
| `reply_builders/` | 回复内容组装 | 不做 DB 查询，不调用 Skill |
| `prompts/` | Prompt 模板集中管理 | 不放业务配置和运行时魔法值 |
| `llm/` | LLM Gateway | 不做业务判断 |
| `rag/` | 向量检索门面 | 不做场景路由 |
| `graphs/` | 复杂多轮写流程子图 | 不承担顶层消息编排 |
| `scenario/` | 场景权限规约和策略校验 | 不处理业务执行 |

## 三、Handler 规则

1. 每个 `scenario_id` 只能有一个明确的 Handler 入口负责处理。
2. Handler 负责流程编排，典型顺序为：解析上下文 -> 调用 Component -> 调用 Skill -> 调用 ReplyBuilder -> 返回 `HandlerResult`。
3. Handler 必须返回明确的 `PendingDirective`，不能依赖隐式规则判断是否保存 Pending。
4. Handler 不直接调用底层 LLM 客户端、向量客户端或外部 HTTP 客户端。
5. Handler 不直接拼接复杂回复文案，统一交给 `reply_builders/`。
6. Handler 捕获可恢复异常后要返回可理解的降级回复，并记录告警日志。
7. Handler 使用上下文中的商品、订单、知识片段前，必须重新校验租户和有效性。

推荐结构：

```python
async def execute(self, decision: ScenarioDecision, context: SessionContext) -> HandlerResult:
    # 解析并校验用户输入中的业务实体
    parsed = await self.resolver.resolve(decision, context)

    # 通过 SkillGateway 执行业务能力
    tool_result = await call_skill("product.get_detail", tenant_id=context.tenant_id, product_id=parsed.product_id)

    # 交给 ReplyBuilder 组装回复
    reply = self.reply_builder.detail(tool_result.data)

    return HandlerResult(
        reply=reply,
        scenario_id=decision.scenario_id,
        pending_directive=PendingDirective.CLEAR,
    )
```

## 四、Component 规则

1. Component 只做参数解析、引用解析和合法性校验。
2. Component 可以读取必要的业务数据用于校验，但不能执行写操作。
3. LLM 抽参结果必须经过 Component 校验后才能传给 Skill。
4. 产品分类、属性、属性值必须基于当前租户配置校验。
5. Component 输出应是明确结构，例如 `ProductReferenceResult`、`OrderReferenceResult`，避免返回无约束字典。
6. Component 不能决定最终回复文案。

## 五、Skill 规则

1. Skill 只接收结构化参数，不接收用户原始文本。
2. Skill 不做意图识别，不重新路由场景。
3. Skill 不自行调用 LLM 或向量检索；需要 LLM/Vector 时由 Handler 或专用服务通过 Gateway 控制。
4. 读 Skill 不提交事务；写 Skill 必须由统一网关管理事务、提交和回滚。
5. Skill 返回值必须可预测，优先使用 `ToolResult` 或明确的数据结构。
6. 写 Skill 必须检查租户、权限、业务状态和幂等 key。

示例：

```python
# 正确：结构化参数
async def get_detail(*, tenant_id: int, product_id: int, db: AsyncSession) -> ToolResult: ...

# 错误：接收用户原始文本
async def get_detail_by_text(*, tenant_id: int, text: str, db: AsyncSession) -> ToolResult: ...
```

## 六、Prompt 与回复规则

1. Prompt 模板只能放在 `backend/app/ai/prompts/`。
2. Prompt 中不写租户配置、业务开关、超时、数量限制等运行时参数。
3. Prompt 输出 JSON 时必须有解析失败降级路径。
4. 回复文案集中在 `reply_builders/` 或专用模板中维护。
5. 面向用户的异常回复应短、明确，并给出下一步选择，例如重新描述、取消、转人工。

## 七、Pending 与 LangGraph 规则

1. `PendingState` 只保存恢复流程所需的最小状态，例如 `scenario_id`、`step`、`graph_thread_id`、`interrupt_id`。
2. 商品候选、订单候选、最近知识引用等普通上下文写入 `SessionContext`，不写入 `PendingState`。
3. Pending 检查顺序固定为：转人工 -> 取消 -> 恢复。
4. 用户表达取消时，必须清理当前 Pending 并返回明确退出回复。
5. 用户表达转人工时，必须优先转人工并清理或冻结当前自动流程。
6. 复杂写流程使用 LangGraph 子图，简单查询不使用 LangGraph。
7. LangGraph 写节点执行前必须完成确认和幂等校验。
8. Graph checkpoint 或 Pending 缺失时，不继续执行写操作，提示用户重新发起或转人工。

## 八、安全与数据规则

1. 所有业务查询必须带 `tenant_id` 过滤。
2. 商品查询默认过滤 `is_active=True`。
3. 上下文中的商品、订单、联系人再次使用前必须重新校验租户归属。
4. 写操作必须使用独立幂等 key，不能依赖 Pending 是否存在来防重复提交。
5. 高风险写操作必须经过用户显式确认。
6. 需要人工处理的场景不能自动执行写操作。
7. 用户输入不得直接拼接 SQL、Prompt 指令或外部请求 URL。
8. 文件、图片、知识库文档处理必须校验租户和上传者权限。

## 九、ScenarioSpec 与策略规则

1. 每个场景必须有清晰的 `scenario_id`。
2. `ScenarioSpec` 必须声明允许调用的 Skill、风险等级、是否允许 LLM、是否允许 Vector、是否允许 Pending。
3. `read_only` 场景不能调用写 Skill，不能设置写流程 Pending。
4. `write_confirm` 场景必须有确认步骤。
5. `human_required` 场景只能引导人工处理。
6. `PolicyGuard` 的违规结果必须降级为安全回复，不能继续执行越权链路。
7. 新增场景时必须补充场景样本、Handler 路由和策略测试。

## 十、日志与 trace 规则

1. 使用 `logging.getLogger(__name__)` 获取 logger。
2. 日志必须使用参数化格式，不使用 f-string 拼接变量。
3. 关键日志必须包含 `tenant_id`、`conversation_id`、`scenario_id` 中可获得的上下文。
4. 日志前缀使用统一中文格式，例如 `【场景进入】`、`【Skill 调用】`、`【外部失败】`。
5. 异常日志使用 `logger.exception()` 或显式 `exc_info=True`。
6. 不在日志中输出明文 API Key、Token、密码、完整身份证号、手机号等敏感信息。
7. 应用级 `trace_id` 由 `app/common/trace/` 管理，业务资源统计由 `ResourceTrace` 管理，两者不要混用。

示例：

```python
logger.info(
    "【场景进入】scenario=%s tenant_id=%s conversation_id=%s",
    scenario_id,
    tenant_id,
    conversation_id,
)
```

## 十一、错误处理规则

1. 可预期业务错误返回可理解回复，不抛出到顶层。
2. 外部服务异常统一转换为项目内异常或降级结果。
3. Redis 读取失败不能静默当作状态不存在；需要记录告警并走安全降级。
4. SessionContext 写入失败可以返回当前回复，但必须记录告警；若后续依赖上下文，提示用户重新描述。
5. LLM 超时或 JSON 解析失败时，优先降级为规则解析、追问或转人工。
6. 向量检索失败时，知识类场景应降级为提示无法确认，而不是编造答案。
7. 所有异常路径必须避免执行写操作。

## 十二、配置与常量规则

1. 全局常量放在 `backend/app/common/constants/`。
2. 业务状态使用枚举或集中常量，不散落裸字符串。
3. 超时、数量限制、TTL、重试次数必须集中配置。
4. `.env` 只放环境差异配置，不放业务规则。
5. 默认值必须保守，不能默认开启高风险写能力。
6. 配置读取失败时应有明确错误或安全默认值。

## 十三、测试规则

1. 新增场景必须覆盖正常、缺参、歧义、多轮恢复、失败降级中适用的路径。
2. 涉及 LLM、Vector、Skill 的场景必须断言 `ResourceTrace`。
3. 读场景要断言不会调用写 Skill。
4. 写场景要断言确认步骤和幂等行为。
5. Pending 场景要断言 `PendingDirective.SET`、`KEEP`、`CLEAR` 的结果。
6. 外部请求相关代码要 mock HTTP 客户端，断言超时、失败、响应解析异常。
7. WebSocket、BackgroundTasks、trace_id 这类基础设施要有独立单元测试，不依赖业务场景间接覆盖。
8. 修复 bug 时补一条能复现问题的测试，再改实现。

## 十四、代码审查清单

| 分类 | 检查项 |
|------|--------|
| 职责 | 是否把识别、抽参、业务执行、回复生成放在正确目录 |
| Handler | 是否只做编排，是否明确返回 `PendingDirective` |
| Component | 是否只做解析和校验，是否避免写操作 |
| Skill | 是否只接收结构化参数，是否校验租户和幂等 |
| Prompt | 是否集中在 `prompts/`，是否有解析失败降级 |
| 安全 | 是否过滤 `tenant_id`，是否避免越权写操作 |
| 日志 | 是否参数化，是否避免敏感信息泄漏 |
| 测试 | 是否覆盖 ResourceTrace、Pending、失败降级和写操作幂等 |
| 文档 | 是否同步更新架构、场景或接口说明 |
