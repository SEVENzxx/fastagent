# FastAgent 文档索引

> 更新日期：2026-07-02

## 文档说明

本目录只保留适合随项目上传到 GitHub 的公开文档，包括项目架构、产品需求、业务场景、开发规范、可观测性和回归测试说明。

## 当前文档

| 文档 | 说明 |
|------|------|
| [`architecture.md`](architecture.md) | 当前项目架构说明：Web 后台、AI 主链路、状态边界、数据存储、前端结构和可观测性 |
| [`requirements/product-requirements.md`](requirements/product-requirements.md) | 当前版产品需求文档：已实现范围、核心流程、后续完善需求和验收标准 |
| [`requirements/scenarios.md`](requirements/scenarios.md) | 当前场景需求说明：识别规则、Handler 边界、风险权限和回归重点 |
| [`development/standards.md`](development/standards.md) | Agent 开发规范、目录职责、Handler/Skill/Pending 边界约束 |
| [`development/observability.md`](development/observability.md) | trace_id 全链路接入方案和可观测性设计 |
| [`evaluation/harness.md`](evaluation/harness.md) | Harness 回归测试说明 |

## 维护原则

文档应以当前代码实现为准。若文档与代码不一致，优先修正文档或在变更代码时同步更新对应说明。

个人简历、面试材料、阶段性审计报告和历史重构计划不放入公开 docs。
