# RVBUST_Code 仓库总览

本仓库用于集中管理 RVBUST 相关的多个项目代码，各项目按分支隔离，请根据需求切换到对应分支查看和使用。

---

## 分支说明

| 分支 | 项目 | 技术栈 | 说明 |
|---|---|---|---|
| `crm-system` | **TechSupportCRM** | FastAPI + Vue 3 + Vite | 客户管理与工单系统（二代版本），支持客户跟进、工单流转、数据导入导出、提醒跟进等功能 |
| `master` | **CRM_New（早期版）** | Node.js + 纯 HTML/JS | CRM 系统初代原型，单文件前端 + Express 后端 + JSON 数据库 |
| `CodedCircleRegistration_v2` | **编码圆拼接工具 v2** | Python + PySide6 + Open3D + RVC SDK | 基于 RVC 深度相机的编码圆点云拼接系统，支持多帧自动配准与彩色融合 |
| `hand-eye-tools` | **手眼标定数据采集助手** | Python + PyQt5 + Open3D + RVC SDK | 基于 RVC X2 相机的手眼标定数据采集 GUI 工具，支持眼在手外/眼在手上 × 标记物/TCP 戳点四种模式，导出 HandEyeManager 兼容格式 |

---

## 快速进入各项目

```bash
# CRM 系统（二代）
git checkout crm-system

# CRM 系统（初代原型）
git checkout master

# 编码圆拼接工具
git checkout CodedCircleRegistration_v2

# 手眼标定数据采集助手
git checkout hand-eye-tools
```

---

## 注意事项

- 各分支之间相互独立，代码不共享
- `main` 分支仅作为仓库入口，不包含可运行代码
- 如需修改某个项目，请在该项目的对应分支上进行开发
