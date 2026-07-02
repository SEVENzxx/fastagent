# FastAgent 可观测性与 trace_id 实现说明

> 更新日期：2026-07-02  
> 适用范围：应用级 `trace_id`、日志注入、外部 HTTP 请求透传、WebSocket 连接追踪、后台任务继承。

本文档说明当前项目中 `trace_id` 的真实实现。它关注的是**日志和跨服务调用链追踪**；AI 业务链路中的 `ResourceTrace` 是另一套用于统计 LLM、向量检索、Skill 调用次数的业务级追踪，不等同于本文的 `trace_id`。

## 设计目标

1. 每个 HTTP 请求、WebSocket 连接、脚本入口尽量拥有一个可关联日志的 `trace_id`。
2. 业务代码不需要显式传递 `trace_id` 参数，通过 `ContextVar` 在当前协程上下文中读取。
3. 所有应用日志自动带上 `[trace_id]`，没有 trace 时显示 `[-]`。
4. 通过项目内 HTTP 客户端调用外部服务时，自动向请求头注入 `X-Trace-Id`。
5. 不改变前端 WebSocket 消息协议，不强制在消息体中返回 trace_id。

## 核心组件

| 文件 | 作用 |
|------|------|
| `backend/app/common/trace/context.py` | 基于 `ContextVar` 保存当前上下文的 `trace_id`，提供 `get_trace_id()`、`set_trace_id()`、`reset_trace_id()`、`ensure_trace_id()` |
| `backend/app/common/trace/middleware.py` | HTTP ASGI 中间件，读取或生成 `X-Trace-Id`，写入 ContextVar，并在响应头返回同一个 `X-Trace-Id` |
| `backend/app/common/logging/filter.py` | `TraceIdFilter`，向每条 `LogRecord` 注入 `trace_id` 字段 |
| `backend/app/logging_config.py` | 注册 `TraceIdFilter`，日志格式包含 `[%(trace_id)s]` |
| `backend/app/integrations/trace_headers.py` | 外部请求头注入工具，负责把当前 `trace_id` 写入 `X-Trace-Id` |
| `backend/app/integrations/base.py` | 外部 HTTP 客户端基类，在 `_send()` 中统一调用 `inject_trace_header()` |

## trace_id 生命周期

### HTTP 请求

`backend/app/main.py` 注册了 `TraceIdMiddleware`：

```python
app.add_middleware(TraceIdMiddleware)
```

HTTP 请求处理流程：

```text
客户端请求
  -> TraceIdMiddleware
      -> 读取请求头 X-Trace-Id
      -> 若没有请求头，则生成 uuid4().hex[:16]
      -> set_trace_id(tid)
  -> FastAPI router / service / integration
  -> 响应头写入 X-Trace-Id
  -> reset_trace_id()
```

覆盖范围包括普通 REST API、企业微信 Webhook、内部 Harness API 和其他通过 FastAPI router 暴露的 HTTP 接口。

### WebSocket 连接

`backend/app/api/v1/ws.py` 在连接入口手动管理连接级 `trace_id`：

```text
WebSocket 建连
  -> 读取 websocket.headers["X-Trace-Id"]
  -> 有值则 set_trace_id(tid)
  -> 无值则 ensure_trace_id()
  -> 整个连接生命周期共享同一个 trace_id
  -> 断开或异常退出时 reset_trace_id()
```

当前实现是**连接级 trace_id**，不是消息级 trace_id。服务端不会把 trace_id 写入 WebSocket 消息体，避免改变前端协议。

### BackgroundTasks

FastAPI `BackgroundTasks` 在当前请求生命周期内执行，能够继承请求处理时的 `ContextVar`。因此从 HTTP 请求派生的后台任务可以读取同一个 `trace_id`。

当前项目依赖这个机制处理 Webhook、知识库等 HTTP 请求触发的后台任务。若未来切换到独立 Worker、消息队列、Celery、Redis Queue 或跨进程任务，需要把 `trace_id` 作为任务参数显式传递。

### Bootstrap 脚本

`backend/app/bootstrap.py` 的 `__main__` 入口已经显式设置和清理 `trace_id`：

```python
ensure_trace_id()
try:
    asyncio.run(bootstrap())
finally:
    reset_trace_id()
```

这保证直接运行 bootstrap 脚本时，脚本执行期间的日志也能带 trace_id。

### LangGraph Resume

当前订单创建、取消等 Graph resume 路径运行在已有请求/协程上下文中时，会自然继承当前 `ContextVar`。项目已有测试覆盖 order.create 与 order.cancel resume 期间 `trace_id` 保持不变。

如果未来出现后台自动恢复 Graph 的路径，需要在后台入口显式设置 `trace_id`。

## 日志格式

`backend/app/logging_config.py` 当前日志格式：

```text
%(asctime)s %(levelname)-8s [%(trace_id)s] %(name)s | %(message)s
```

`TraceIdFilter` 会在日志输出前设置：

```text
record.trace_id = get_trace_id() or "-"
```

因此日志表现为：

```text
2026-07-02 10:30:00 INFO     [a1b2c3d4e5f67890] app.ai.entry.processor | 消息开始处理
2026-07-02 10:30:01 INFO     [-] app.main | 应用启动
```

没有 trace 上下文的启动日志、长期后台任务日志会显示 `[-]`，这是预期行为。

## 外部 HTTP 请求透传

项目通过 `backend/app/integrations/trace_headers.py` 注入 trace header：

```text
当前 ContextVar 有 trace_id
  -> headers 中不存在任意大小写形式的 X-Trace-Id
  -> 注入 X-Trace-Id: <trace_id>
```

规则：

- 若当前没有 `trace_id`，不注入请求头。
- 若调用方已经传入 `X-Trace-Id`、`x-trace-id` 或其他大小写形式，不覆盖原值。
- 返回新的 headers 字典，不修改入参。

`BaseClient._send()` 会统一调用 `inject_trace_header()`，因此继承 `BaseClient` 或复用其发送逻辑的外部客户端都会自动带上 `X-Trace-Id`。当前测试覆盖了以下路径：

- `BaseClient`
- `LLMClient` 的 HTTP 调用路径
- `QdrantVectorClient`
- `EmbeddingClient`
- `RerankerClient`
- `WeComOutboundClient`

注意：直接使用第三方 SDK 的调用链不一定经过 `BaseClient`，例如部分 LiteLLM / Langfuse 内部调用有自己的追踪机制。应用日志 trace_id 与 Langfuse trace_id 是两套不同标识，不应混用。

## ResourceTrace 与 trace_id 的区别

| 项 | trace_id | ResourceTrace |
|----|----------|---------------|
| 目的 | 串联一次请求/连接/任务的日志和外部调用 | 统计 AI 业务链路资源使用情况 |
| 实现位置 | `app/common/trace/*` | `app/ai/trace.py`、`HandlerResult.resource_trace` |
| 传播方式 | `ContextVar[str]` | `ContextVar[dict]` + Handler 汇总 |
| 典型字段 | `X-Trace-Id`、日志 `[trace_id]` | `llm_calls`、`vector_calls`、`skill_calls`、`sql_calls` |
| 面向对象 | 运维排查、跨服务追踪 | Harness 断言、场景权限校验 |

两者可以同时存在：同一次用户请求有一个 `trace_id`，其中某个 AI 场景处理结果还会包含 `ResourceTrace`。

## 已知边界

1. `TraceIdMiddleware` 只处理 HTTP scope，不处理 WebSocket；WebSocket 由 `ws.py` 显式处理。
2. 连接级 WebSocket trace_id 无法区分同一连接内的多条业务消息。
3. 独立 Worker、队列任务、跨进程任务不会自动继承 `ContextVar`，需要显式传递。
4. 启动阶段或长期后台 worker 日志可能显示 `[-]`，除非入口显式设置 trace_id。
5. `BaseClient._request()` 仍有部分日志手动拼接 `trace_id=%s`，同时日志格式也会自动带 `[trace_id]`。这属于冗余信息，不影响功能。

## 相关测试

| 测试文件 | 覆盖内容 |
|----------|----------|
| `backend/tests/test_trace.py` | TraceIdFilter、TraceIdMiddleware、BackgroundTasks 继承 |
| `backend/tests/test_ws_trace.py` | WebSocket 继承、生成和重置 trace_id |
| `backend/tests/test_bootstrap_trace.py` | bootstrap 脚本入口设置和清理 trace_id |
| `backend/tests/test_integration_trace.py` | 外部 HTTP 请求注入 `X-Trace-Id` |
| `backend/tests/test_order_handler.py` | Graph resume 路径继承 trace_id |

## 维护建议

- 新增 HTTP router 不需要额外处理 trace_id，默认经过中间件。
- 新增 WebSocket 入口时，需要像 `ws.py` 一样显式设置和清理 trace_id。
- 新增外部 HTTP 客户端时，优先继承 `BaseClient` 或复用 `inject_trace_header()`。
- 新增独立脚本、队列消费者或后台 worker 时，在入口处调用 `ensure_trace_id()`，结束时调用 `reset_trace_id()`。
- 新增测试时不要断言固定 trace_id 值，除非请求显式传入 `X-Trace-Id`。
