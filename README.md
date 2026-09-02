# 技术支持工单与客户管理系统

基于 Express + lowdb + 单文件 HTML 的极简工单管理系统，专为 RVC 相机技术支持团队设计。

## 在线演示

- **生产环境**：http://120.55.245.72:38000
- **技术栈**：Express 4.x + lowdb (JSON DB) + Vanilla JS

## 功能特性

| 模块 | 功能 |
|------|------|
| **工单管理** | 创建、编辑、删除、状态流转（待处理→处理中→等待回复→已解决→已关闭） |
| **工单编号** | 自动生成格式 `TYPE-YYMMDD-XXX`（RVC/VDA 分类，每日自增） |
| **客户管理** | 客户信息、设备清单、**最近互动**（显示最新工单） |
| **智能解析** | 自然语言输入自动识别客户、优先级、问题类型 |
| **RVC 分类** | 点云调试、硬件故障、软件问题、SDK开发、手眼标定、需求沟通、样品测试、相机选型 |
| **权限控制** | 管理员可查看全部，工程师只能编辑自己负责的工单 |
| **图片附件** | 上传/粘贴图片，Base64 内联存储 |
| **数据导出** | **CSV 导出**（工单/客户，Excel 兼容，UTF-8 带 BOM） |
| **统计报表** | 工单状态、优先级、工程师工作量、分类分布 |

## 快速开始

### 本地开发

```bash
cd server
npm install
node server.js
```

访问 http://localhost:3000

**默认账号**：
- `admin` / `admin123`（管理员）
- `zhangsan` / `123456`（工程师）

### 生产部署

```bash
# 服务器
ssh root@120.55.245.72
cd /root/crm_new
./update.sh   # 自动 git pull + npm install + pm2 restart
```

## 项目结构

```
tech-support-crm/
├── project/
│   └── index.html          # 前端单文件应用 (~2150 行)
├── server/
│   ├── server.js           # Express 后端
│   ├── database.js         # lowdb 数据层
│   ├── package.json        # 依赖
│   └── init_db.js          # 数据库初始化
└── update.sh               # 服务器自动更新脚本
```

## Git 工作流

| 环境 | 操作 |
|------|------|
| 本地开发 | 修改代码 → `git commit` → `git push origin main` |
| 服务器更新 | `cd /root/crm_new && ./update.sh` |

## 已知问题

1. ~~工单编号重复~~ ✅ 已修复：改为 `TYPE-YYMMDD-XXX` 每日自增格式
2. 密码明文存储（内部使用，暂可接受）
3. 图片附件 Base64 内联导致 `db.json` 膨胀（建议后续改为文件存储）
4. ~~缺少数据导出~~ ✅ 已支持 CSV 导出
5. 工单/客户列表无分页（数据量大时性能下降）
6. 登录状态不持久（刷新后需重新登录）
7. 搜索功能较简单（仅支持客户名称/联系人/电话）

## API 接口

| 接口 | 方法 | 权限 | 说明 |
|------|------|------|------|
| `/api/login` | POST | 公开 | 登录，返回 token |
| `/api/tickets` | GET/POST | 需登录 | 工单列表 / 创建工单 |
| `/api/tickets/:id` | GET/PUT/DELETE | 需登录 | 工单详情 / 更新 / 删除（仅管理员） |
| `/api/tickets/:id/comments` | POST | 需登录 | 添加工单评论 |
| `/api/customers` | GET/POST | 需登录 | 客户列表 / 创建客户 |
| `/api/customers/:id` | GET/PUT/DELETE | 需登录 | 客户详情 / 更新 / 删除（仅管理员） |
| `/api/export/tickets` | GET | 需登录 | 导出工单 CSV |
| `/api/export/customers` | GET | 需登录 | 导出客户 CSV |
| `/api/stats` | GET | 需登录 | 统计数据（Dashboard） |
| `/api/reminders` | GET/POST | 需登录 | 通知列表 / 创建通知 |

## License

MIT
