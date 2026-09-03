# CRM_New（旧版归档）

> ⚠️ **本分支为历史归档，不再维护**。当前版本的 CRM 工单与客户管理系统请切换到 **`crm_system`** 分支。

## 说明

CRM 工单与客户管理系统早期版本归档，Node.js（Express）+ 单文件 HTML 前端 + JSON 数据库（lowdb）。

本分支保留了早期开发与部署脚本（含 `deploy.ps1` / `deploy_remote.py` / `scripts/update-server.sh` 等），仅作历史存档用途，不建议直接运行或部署。

## 现行版本入口

```bash
# CRM 工单与客户管理系统（当前版）
git checkout crm_system
```

| 分支 | 说明 |
|------|------|
| `crm_system` | ✅ 当前维护版：Express + lowdb + 单文件前端，含工单/客户/工作日志/图片上传 |
| `master` | 🗄️ 本分支：旧版归档（含部署脚本）|
