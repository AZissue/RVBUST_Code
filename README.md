# RVBUST_Code 仓库总览

本仓库用于集中管理 RVBUST 相关的多个项目代码，各项目按分支隔离，请根据需求切换到对应分支查看和使用。

---

## 分支说明

| 分支 | 项目 | 技术栈 | 说明 |
|---|---|---|---|
| `crm_system_v2` | **CRM 工单与客户管理系统 V2（开发中）** | NestJS + Prisma + React + Vite（monorepo） | 现行 CRM 的重构版：多角色账号审批、工单流转与 AI 快速开单解析、客户 360、设备台账、借测与返修管理，含 e2e 测试与 Docker 部署 |
| `crm_system` | **CRM 工单与客户管理系统 V1（现网）** | Node.js Express + lowdb + 单文件前端 | 客户管理与工单系统：客户跟进、工单流转、工作日志、图片上传、数据导入导出、已解决工单自动关闭等；V2 功能迁移完成后将退役 |
| `MultiCameraCalibration` | **多相机外参标定与点云拼接** | Python + PySide6 + Open3D + RVC SDK | N 相机外参标定（RANSAC + SVD + 四元数平均），非对称圆标定板检测与位姿法标定，编码圆标记检测，单相机多站位模式，离线会话批量处理，点云拼接与后处理 |
| `CodedCircleRegistration_v2` | **编码圆拼接工具 v2** | Python + PySide6 + Open3D + RVC SDK | 基于 RVC 深度相机的编码圆点云拼接系统，支持多帧自动配准与彩色融合 |
| `rvc-vision-studio` | **RvcVisionStudio** | C++ / Qt6 + QtNodes + PCL / VTK | 拖拽式零代码 3D 点云流程编排与测量平台，支持 ROI 框选、几何拟合、尺寸测量、多视窗与异步执行引擎 |
| `pointcloud-search` | **PointCloudSearch** | C++20 + Qt 6.8 + VTK + PCL | 模块化点云查找 / 分析桌面程序（节点式图形化流程编排）+ C++ SDK，面向 RVC 3D 相机客户，支持 ROI 框选、降采样、聚类、平面检测、方案保存加载等 |
| `master` | **CRM 早期版本归档** | Node.js + 纯 HTML/JS | CRM 系统早期版本归档（含历史部署脚本），已由 `crm_system` / `crm_system_v2` 替代 |

> 手眼标定相关工具（HandEyeManager 数据采集助手等）代码保存在本地 `D:\RVC_SRC\hand-eye-tools`，未纳入本仓库。

---

## 快速进入各项目

```bash
# CRM 工单与客户管理系统 V2（重构版，开发中）
git checkout crm_system_v2

# CRM 工单与客户管理系统 V1（现网）
git checkout crm_system

# 多相机外参标定与点云拼接
git checkout MultiCameraCalibration

# 编码圆拼接工具
git checkout CodedCircleRegistration_v2

# RvcVisionStudio（拖拽式零代码点云测量平台）
git checkout rvc-vision-studio

# PointCloudSearch（模块化点云查找/分析桌面程序）
git checkout pointcloud-search

# CRM 早期版本归档
git checkout master
```

---

## 注意事项

- 各分支之间相互独立，代码不共享
- `main` 分支仅作为仓库入口，不包含可运行代码
- 如需修改某个项目，请在该项目的对应分支上进行开发
- CRM 相关：现网使用 `crm_system`（V1），新功能与重构统一在 `crm_system_v2`（V2）上开发
