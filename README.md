# 技术支持工单与客户管理系统（CRM）

基于 Express + lowdb + 单文件 HTML 的工单管理系统，专为 RVC 相机技术支持团队设计。

- **技术栈**：Express 4.x + lowdb (JSON DB) + Vanilla JS 单文件前端
- **默认端口**：8080（`PORT` 环境变量可覆盖）

## 功能特性

| 模块 | 功能 |
|------|------|
| **工单管理** | 创建、编辑、删除、状态流转（待处理→处理中→等待回复→已解决→已关闭） |
| **工单编号** | 自动生成格式 `TYPE-YYMMDD-XXX`（RVC/VDA 分类，每日自增） |
| **客户管理** | 客户信息、设备清单、**最近互动**（显示最新工单）；客户 ID 后端自动生成 |
| **工作日志** | 按时间记录工作内容，可关联工单；工程师只见自己的，管理员看全部 |
| **智能解析** | 自然语言输入自动识别客户、优先级、问题类型 |
| **RVC 分类** | 点云调试、硬件故障、软件问题、SDK开发、手眼标定、需求沟通、样品测试、相机选型 |
| **权限控制** | 管理员可查看全部，工程师只能编辑自己负责的工单 |
| **图片附件** | 文件上传（multer，10MB 限制，存 `project/uploads/`）或粘贴图片 |
| **自动关闭** | 已解决工单超过 7 天自动转为已关闭 |
| **数据导出** | **CSV 导出**（工单/客户，Excel 兼容，UTF-8 带 BOM） |
| **统计报表** | 工单状态、优先级、工程师工作量、分类分布 |

## 快速开始

```bash
cd server
npm install
node server.js
```

访问 http://localhost:8080

**默认账号**：
- `admin` / `admin123`（管理员）
- `zhangsan` / `123456`（工程师）

## 项目结构

```
crm_system/
├── project/
│   └── index.html          # 前端单文件应用
│   └── uploads/            # 图片附件存储（运行时生成）
├── server/
│   ├── server.js           # Express 后端（含上传/worklog 路由）
│   ├── database.js         # lowdb 数据层
│   ├── package.json        # 依赖
│   ├── init_db.js          # 数据库初始化
│   └── data/db.json        # 数据文件（运行时生成，不入库）
└── README.md
```

## 主要 API

| 接口 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/api/login` | POST | 公开 | 登录，返回 token |
| `/api/tickets` | GET/POST | 需登录 | 工单列表 / 创建工单 |
| `/api/tickets/:id` | GET/PUT/DELETE | 需登录 | 工单详情 / 更新 / 删除（仅管理员） |
| `/api/tickets/:id/comments` | POST | 需登录 | 添加工单评论 |
| `/api/customers` | GET/POST | 需登录 | 客户列表 / 创建客户 |
| `/api/customers/:id` | GET/PUT/DELETE | 需登录 | 客户详情 / 更新 / 删除（仅管理员） |
| `/api/worklogs` | GET/POST | 需登录 | 工作日志列表 / 创建 |
| `/api/upload` `/api/upload/multi` | POST | 需登录 | 图片上传（单张/批量，≤10MB） |
| `/api/export/tickets` | GET | 需登录 | 导出工单 CSV |
| `/api/export/customers` | GET | 需登录 | 导出客户 CSV |
| `/api/stats` | GET | 需登录 | 统计数据（Dashboard） |

## 已知限制

1. 密码明文存储（内部使用）
2. 工单/客户列表分页加载 20 条/页，超大历史数据查询需后端进一步优化
3. 登录状态不持久（刷新后需重新登录）

## License

MIT
