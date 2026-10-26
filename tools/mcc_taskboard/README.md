# MCC 评估与 Agent 任务看板

独立、仅本机回环的评估和正式任务服务。使用 Python 标准库，不修改主程序、不增加第三方依赖。

## 启动

在仓库根目录：

```bash
"D:/Program Files/Anaconda/envs/rvc/python.exe" tools/mcc_taskboard/run.py
```

默认地址：`http://127.0.0.1:7788`。若该端口被其他进程占用，不终止现有进程，可改用：

```bash
"D:/Program Files/Anaconda/envs/rvc/python.exe" tools/mcc_taskboard/run.py --port 7789
```

本次交付实际运行地址为 `http://127.0.0.1:7789`，因为 `7788` 已被另一个 `node.exe server.js` 进程监听。

## 网页与任务

- 点击“运行项目评估”执行高信号离线脚本，记录退出码、耗时和日志；失败项自动生成 `AUTO-*` 任务并去重。
- 正式任务包含证据、影响文件、实施要求和验收命令。状态为 `open → claimed → in_progress → review → done`。
- Agent 可接取、释放和更新任务，历史写入 `data/tasks.json`。评估写入 `data/evaluation.json`。
- 人工任务不会因相关测试通过而自动关闭；实机、硬件 GPU 和客户机验收需另行执行。

## Agent API

```text
GET  /api/summary
GET  /api/tasks?status=open
GET  /api/tasks/{id}
GET  /api/evaluation
POST /api/evaluate
POST /api/tasks/{id}/claim    {"agent":"agent-name"}
POST /api/tasks/{id}/release  {"agent":"agent-name"}
POST /api/tasks/{id}/status   {"agent":"agent-name","status":"in_progress","note":"开始修复"}
```

## 验证

```bash
"D:/Program Files/Anaconda/envs/rvc/python.exe" tools/mcc_taskboard/tests/test_store.py
"D:/Program Files/Anaconda/envs/rvc/python.exe" tools/mcc_taskboard/tests/test_server.py
node --check tools/mcc_taskboard/static/app.js
```

测试使用临时目录和临时端口，不影响正式任务数据，不初始化实体设备。
