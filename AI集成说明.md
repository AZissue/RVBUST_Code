# 统一 AI API 管理与快速工单解析

日期：2026-09-04。基于现有 React / NestJS / Prisma / PostgreSQL V2 增量实现。

## 本次范围

- 新增系统设置 → AI 模型设置，包含 Provider 管理、功能分配、最近 100 条调用日志。
- 实际接入路径：工作台快速工单语义解析 → 人工确认 → 原有工单创建/更新。
- 保留 RuleBasedParser。AI 未配置、停用、无密钥、认证/额度错误、网络失败、超时、格式无效时自动降级。
- Work Log 多草稿入口仍使用原来的规则拆分，不擅自改为自动 AI 写入。
- 工作记录整理、日报/周报/月报、AI 助手、知识问答只预留配置、模板及统一调用入口；未实现这些功能的完整 AI 页面。左侧“AI 助手（后续）”保留。
- 未新增公共任意 `/ai/chat` 代理，避免普通用户绕过业务权限随意消费模型额度。业务模块内部复用 `AIService.chat()`。

## 配置和密钥

数据库采用三张独立表，不存入会被普通设置接口返回的 `system_settings`：

| 表 | 内容 |
| --- | --- |
| `ai_provider_configs` | 类型、名称、地址、模型、启用/默认、参数、加密后的 API Key |
| `ai_feature_configs` | 功能默认继承/Provider 覆盖、模型、Temperature、输出 Token |
| `ai_usage_logs` | requestId、用户、功能、Provider/模型快照、结果、耗时、次数及 Token |

增量迁移：`apps/api/prisma/migrations/202609040002_ai_gateway/migration.sql`。不改写原工单、工作事项、工作记录。数据库部分唯一索引确保只有一个默认 Provider；配置修改使用事务锁。默认 Provider 必须启用。

API Key 的保护分两层：

1. 浏览器仅在管理员输入新 Key 时短暂持有明文。保存前调用 `/api/ai/key-exchange` 获取临时公钥，通过 WebCrypto AES-256-GCM + RSA-OAEP/SHA-256 混合加密；Network 保存请求只有 `sealedApiKey` 密文。后端拒绝明文 `apiKey` 字段。
2. 后端解封后，使用独立主密钥进行 AES-256-GCM 加密再保存数据库。每次随机 IV，Provider ID 作为附加认证数据，防止跨记录挪用密文。主密钥为根目录 `.env` 中的 `AI_CONFIG_ENCRYPTION_KEY`，绝不能设为 `VITE_` 变量或上传 Git。

配置接口只返回 `hasApiKey` 和固定掩码 `********`，不返回明文、密文或主密钥。编辑留空保留原 Key；更换 Base URL 必须重新输入 Key。后端才会向 Provider 发送 Authorization。响应若回显 Key 会被拒绝；错误不透传供应商原始响应体。

**不能声称浏览器在任何时刻都接触不到 Key**：用户手动输入时，输入框和 JS 内存会短暂包含明文；加密提交只保护 Network 请求展示，不防恶意浏览器扩展、XSS 或本机管理员。已保存的 Key 无读取接口。生产部署仍必须 HTTPS，公钥提交不替代 TLS；LAN 明文 HTTP 也不满足 WebCrypto 安全上下文要求。

首次配置后端加密主密钥：

```powershell
npm run ai:init-key
```

此命令只初始化空配置，已有有效密钥保持不变，不输出密钥。重启 API 生效。务必单独安全备份 `.env`；丢失或更换主密钥会使旧 Provider Key 无法解密，必须重新输入。备份文件和 `.env` 应限制到运行账户可读。多 API 实例的临时公钥交换需要粘性会话；当前为单机模块化单体。

## 支持的 Provider

DeepSeek、Kimi/Moonshot、OpenAI、自定义 OpenAI-Compatible 均注册到兼容 Chat Completions 的适配器。

- 注册位置：`apps/api/src/ai/ai.registry.ts`。
- DeepSeek / Kimi / OpenAI 实际调用封装共用 `apps/api/src/ai/openai-compatible.adapter.ts`，不在页面内分别拼请求。
- 网络传输、域名解析和地址限制：`apps/api/src/ai/ai.transport.ts`。
- 统一业务入口和默认配置解析：`apps/api/src/ai/ai.service.ts`。
- Adapter 契约：`apps/api/src/ai/ai.types.ts`，包括 chat、testConnection、listModels、validateConfig。

添加自定义接口：新增 Provider → 选择 OpenAI-Compatible → 填写名称、Base URL、实际 Key 和模型 → 保存 → 测试连接 → 启用并选择默认。Base URL 是接口前缀，不包含 `/chat/completions`；例如 `https://company.example/v1`。模型名完全可编辑，不预置永远有效的模型。可用已保存配置查询 `/models`，不支持查询的服务可手填。

兼容性选项：`max_tokens` / `max_completion_tokens`、是否省略 Temperature、是否发送 JSON 模式参数。模型不支持某参数时按其官方文档调整；无论是否发送 JSON 模式参数，业务结果都必须通过后端严格校验。

Claude/Gemini 原生协议**尚未实现**。未来实现同一 Adapter 接口并注册，再扩展 Provider 类型与 UI 即可；若企业网关已经将其转换为 OpenAI-Compatible 协议，可先按自定义接口配置。

默认阻止内网/回环/链路本地地址、不安全协议、URL 凭据与查询参数；不跟随重定向，DNS 地址验证后固定到连接，响应大小最多 1 MiB。受信内网接口由后端 `.env` 的 `AI_ALLOWED_INTERNAL_ORIGINS` 设置精确 origin 白名单（含协议及端口，逗号分隔），不支持通配符。只有可信企业服务才应加入；例外允许 HTTP 会失去传输加密，不建议非回环环境使用。

## 默认和功能覆盖

在 Provider 编辑中选择“启用”及“系统默认 AI”。AI 功能分配支持“使用系统默认”或指定 Provider；模型空值继承该 Provider 默认模型，Temperature/Token 空值继承 Provider 参数。

删除/停用当前默认后不会自动选用其他服务商；UI 显示未配置默认，规则解析继续工作。删除被功能指定的 Provider 会清除外键，但保留 `useSystemDefault=false`，该功能暂不可用并降级，避免未经确认把数据发送到别的服务商。

功能键：quick_ticket_parser、work_record_summary、daily_report、weekly_report、monthly_report、ai_assistant、knowledge_qa。只有 quick_ticket_parser 本次真正启用。

## 解析、校验和降级

`QuickTicketsService` → `AIParser` → `AIService.chat()` → 功能覆盖/全局默认 → Adapter。

提示词集中在 `apps/api/src/ai/prompt-templates.ts`。只发送原文及最多 20 个相关客户名、人员名、设备型号候选，不发送数据库 ID、联系人、完整客户表或设备序列号。

模型只能输出 customerText、issue、assigneeText、priority、deviceText 五个字符串，禁止额外字段和 ID。后端校验类型、长度、优先级枚举及原文依据，实体和问题描述必须来自原文，拒绝模型补充不存在的客户、人员、处理结果。客户/人员仍使用原来的模糊匹配；设备仅在匹配客户内查找，多个候选不自动选择。最后仍需用户确认，解析调用不创建任何业务实体。

超时默认 30 秒，可设 1～60 秒，两次尝试共用一个总期限。仅网络或 5xx 服务异常最多重试一次；认证、权限、404、额度、格式、超时等错误不重试。单个用户最多一个在途 AI 调用，全进程最多 8 个。AI 错误不会影响普通页面或直接创建工单。

调用日志不保存原文、Prompt、完整模型响应或密钥。供应商缺失/失败请求未报告的 Token 为 null，不伪造为零；日志不是账单的精确替代。最新 100 条可在页面查看，当前无自动归档/清理策略。AI 日志写入失败只记录 requestId 告警，不抛给业务。

## 管理接口

所有 `/api/ai/*` 接口仅管理员可用。普通内部用户经现有权限控制的 `/api/tickets/quick/parse` 使用 AI。

| 方法 | 路由 |
| --- | --- |
| GET | `/api/ai/key-exchange`、`/api/ai/providers`、`/api/ai/features`、`/api/ai/usage` |
| POST | `/api/ai/providers`、`/api/ai/providers/:id/test`、`/api/ai/providers/:id/models` |
| PUT | `/api/ai/providers/:id`、`/api/ai/features/:key` |
| DELETE | `/api/ai/providers/:id` |

测试连接会真正请求所选模型的最小 JSON 回复，可能产生少量费用。明确区分 401、403、404、429、超时、网络及格式错误。

## 测试结果和限制

- 单元测试：40 项通过。
- PostgreSQL API 集成：39 项通过，包括 Provider/功能配置、切换、密文保存、权限、无配置降级、无效 JSON、幻觉实体、非法 ID、超时、错误码、最多一次重试和 Token 日志。
- Playwright：3 条新旧端到端流程通过，包括配置刷新持久化、浏览器提交仅密文、重新编辑拿不到保存的 Key、主题和移动端、普通工单/工作事项/工作记录回归。
- 生产构建通过。
- 模拟接口仅运行在隔离测试 schema 中，使用运行时随机测试凭据，结束删除 Provider；没有给正式库填入虚假 Key。
- **真实 DeepSeek、Kimi、OpenAI、第三方兼容接口：均尚未连接验证，因为没有用户实际 API Key。代码和接口已经完成，但需要实际 API Key 才能进行最终连接测试。**

## 本机部署记录

运行目录为 `D:\RVBUST\tech-support-crm-v2`，入口为 `http://127.0.0.1:5173/settings/ai`。已应用增量迁移并初始化本机专用加密主密钥；未添加任何正式 Provider。健康检查和浏览器验收通过，业务数据仍为 1 张工单、2 条工作事项、1 条工作记录。

本次工作区 `outputs/before-ai-providers-20260904.dump` 为部署前 public schema 备份，`outputs/before-ai-source-20260904` 为部署前源码备份（不含密钥、依赖和附件）。新生成的后端主密钥保存在运行目录 `.env`，应另行安全保管。

## 官方接口依据

- [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [OpenAI Structured Outputs / JSON 模式](https://developers.openai.com/api/docs/guides/structured-outputs)
- [DeepSeek API](https://api-docs.deepseek.com/)
- [Kimi Chat Completions](https://platform.kimi.ai/docs/api/chat)

当前模型名及账户权限以服务商实际返回为准；此文档不保证任何特定模型永久可用。
