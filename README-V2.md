# 技术支持系统 V2

2026-09-04 更新：仪表盘快速输入改为“解析并确认工单”；我的工作改为当前负责人名下的工单视图。原事项保留为历史兼容入口，工作记录继续独立保存。数据迁移、匹配规则和验收见 [快速工单改造说明.md](快速工单改造说明.md)。

V2 第一阶段是一个面向内部技术支持工作的模块化单体。它将问题、任务和实际工作事实明确拆分：

- **Ticket（工单）**：客户问题、技术异常和需要持续跟进的问题。
- **Work Item（工作事项）**：培训、文档、测试、研发协同、软件工具等非工单任务。
- **Work Log（工作记录）**：实际完成的工作事实，可关联工单、工作事项、客户或项目，也可独立存在。

## 技术架构

- Web：React、TypeScript、Vite、React Router、Lucide
- API：NestJS 模块化单体、DTO 校验、后端 RBAC 与对象级权限
- 数据：PostgreSQL、Prisma ORM、版本化 migration
- 安全：bcrypt 密码哈希、服务端 Session、HttpOnly Cookie、登录限流、Helmet、安全审计
- 交付：Docker Compose；前端 Nginx 反向代理 `/api`

## 目录结构

```text
apps/api/                 NestJS API 与 Prisma schema
apps/web/                 React Web 应用
e2e/                      Playwright 浏览器流程
migration/import-v1.ts    V1 lowdb 预检/导入工具
docker-compose.yml        PostgreSQL、API、Web 编排
```

## 本地启动

需要 Node.js 20+、npm 和 PostgreSQL 16+。

```powershell
Copy-Item .env.example .env
# 编辑 .env，为数据库和四个种子账号设置独立强密码
npm install
npm run db:migrate
npm run db:seed
npm run dev
```

打开 `http://127.0.0.1:5173`。API 位于 `http://127.0.0.1:3001/api`，健康检查为 `/api/health`。

本机当前还提供了忽略版本控制的便携 PostgreSQL 运行时 `.runtime/pgsql`；长期开发和部署建议使用系统 PostgreSQL 或 Docker，不要提交 `.runtime` 和 `.env`。

## 测试账号

种子账号为 `admin`、`support`、`employee`、`customer`。密码分别由 `.env` 中的 `SEED_*_PASSWORD` 提供；源码和文档不保存真实密码。`customer` 第一阶段只有账号及权限数据结构，没有完整门户 UI。

## 测试

```powershell
npm run build
npm test
npm run test:e2e -w apps/api
$env:PLAYWRIGHT_BROWSERS_PATH='.runtime\ms-playwright'
npm run test:e2e
npm audit
```

## Docker 运行

先创建 `.env` 并填写强密码，然后执行：

```powershell
docker compose up --build
```

公网部署时由 Caddy、Nginx 或云负载均衡器终止 HTTPS，只开放 Web 入口；PostgreSQL 不暴露公网。生产环境应使用独立密钥管理、受限数据库账号、持久卷、自动备份和反向代理限流。

## V1 数据迁移

迁移工具默认仅预检，且绝不导入 V1 明文密码：

```powershell
npm run db:import:v1 -- D:\RVBUST\tech-support-crm\server\data\db.json
npm run db:import:v1 -- D:\RVBUST\tech-support-crm\server\data\db.json --apply --owner=support
```

先审核预检结果和原始数据，再执行 `--apply`。V1 工作日志迁为 Work Log；V1 没有 Work Item，内部任务需审核后单独建立，不能伪装成工单。

## 快速记录约定

第一阶段使用确定性标点拆分，将一段 `rawText` 生成多条 `DRAFT` Work Log，共享 `aiExtractionId`。用户确认后才转为 `CONFIRMED`。后续 AI 只能整理和分类已有事实，不得补写不存在的工作。
