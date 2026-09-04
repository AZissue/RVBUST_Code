# 技术支持系统 V2

当前分支：`crm_system_v2`。这是独立的 V2 项目分支，旧版保留在 `crm_system`，main 保持仓库导航用途。

V2 使用 React + TypeScript + NestJS + PostgreSQL + Prisma，分别管理工单（问题）、工作事项（任务）和工作记录（事实）。

启动、环境配置、测试和部署请参阅 [README-V2.md](README-V2.md)，当前实现范围见 [V2开发进度.md](V2开发进度.md)。

本分支仅包含源码与数据库迁移，不包含本机数据库、真实密码、上传附件、运行时或依赖目录。首次运行请配置 `.env` 并初始化独立数据库；浏览器测试通过环境变量 `SEED_ADMIN_PASSWORD` 登录，只应针对测试数据库执行。

## 原仓库分支导航

本仓库用于集中管理 RVBUST 相关的多个项目代码，各项目按分支隔离，请根据需求切换到对应分支查看和使用。

---

## 分支说明

| 分支 | 项目 | 技术栈 | 说明 |
|---|---|---|---|
| `crm_system` | **CRM 工单与客户管理系统** | Node.js Express + lowdb + 单文件前端 | 客户管理与工单系统，支持客户跟进、工单流转、工作日志、图片上传、数据导入导出、已解决工单自动关闭等功能（替代早期 crm-system / master 分支版本） |
| `MultiCameraCalibration` | **多相机外参标定与点云拼接** | Python + PySide6 + Open3D + RVC SDK | N 相机外参标定（RANSAC + SVD + 四元数平均），非对称圆标定板检测与位姿法标定，编码圆标记检测，单相机多站位模式，离线会话批量处理，点云拼接与后处理 |
| `master` | **CRM_New（旧版归档）** | Node.js + 纯 HTML/JS | CRM 系统早期版本归档（含部署脚本），已由 `crm_system` 分支替代 |
| `CodedCircleRegistration_v2` | **编码圆拼接工具 v2** | Python + PySide6 + Open3D + RVC SDK | 基于 RVC 深度相机的编码圆点云拼接系统，支持多帧自动配准与彩色融合 |
| `hand-eye-tools` | **手眼标定数据采集助手** | Python + PyQt5 + pyqtgraph + RVC SDK | 基于 RVC 相机的手眼标定数据采集 GUI 工具，支持眼在手外/眼在手上 × 标记物/TCP 戳点四种模式，导出 HandEyeManager 兼容格式 |
| `rvc-vision-studio` | **RvcVisionStudio** | C++ / Qt6 + QtNodes + PCL / VTK | 拖拽式零代码 3D 点云流程编排与测量平台，支持 ROI 框选、几何拟合、尺寸测量、多视窗与异步执行引擎 |
| `pointcloud-search` | **PointCloudSearch** | C++20 + Qt 6.8 + VTK + PCL | 模块化点云查找 / 分析桌面程序（节点式图形化流程编排）+ C++ SDK，面向 RVC 3D 相机客户，支持 ROI 框选、降采样、聚类、平面检测、方案保存加载等 |

---

## 快速进入各项目

```bash
# CRM 工单与客户管理系统（当前版）
git checkout crm_system

# 多相机外参标定与点云拼接
git checkout MultiCameraCalibration

# CRM 系统（初代原型）
git checkout master

# 编码圆拼接工具
git checkout CodedCircleRegistration_v2

# 手眼标定数据采集助手
git checkout hand-eye-tools

# RvcVisionStudio（拖拽式零代码点云测量平台）
git checkout rvc-vision-studio

# PointCloudSearch（模块化点云查找/分析桌面程序）
git checkout pointcloud-search
```

---

## 注意事项

- 各分支之间相互独立，代码不共享
- `main` 分支仅作为仓库入口，不包含可运行代码
- 如需修改某个项目，请在该项目的对应分支上进行开发
