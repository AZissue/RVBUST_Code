# 推送指南（2026-09-10）

## 当前状态

本地已提交改动（commit: `85429c3`）到 `hand-eye-tools` 分支，包括：
- `src/ui/SidePanel.{h,cpp}`：UI 布局重构（操作日志 + 文件预览等分空间）
- `src/app/MainWindow.cpp`：主窗口前台激活修复 + 禁用自动质检刷新
- `STATUS.md`：本轮改动记录

分支追踪：`hand-eye-tools` → `origin/hand-eye-tools` (ahead 8, behind 2)

## 推送步骤（按 AGENTS.md 流程）

### 第 1 步：推送到 AICode (keybord317/AICode)

> **前置**：确保 AICode remote 已配置，分支为 `handeye-calib-tool/tools-panel`

如果 AICode 尚未有 `handeye-calib-tool/tools-panel` 分支，则需要创建并推送：

```bash
# 1. 检查 AICode 的分支
git fetch AICode
git branch -r | grep AICode

# 2. 基于当前 hand-eye-tools 创建或更新远端分支
#    选项 A：如果 AICode 有 handeye-calib-tool/tools-panel，则：
git push AICode hand-eye-tools:handeye-calib-tool/tools-panel

#    选项 B：如果需要新建分支，同样使用上述命令

# 3. 验证推送
git fetch AICode
git branch -r | grep handeye-calib-tool/tools-panel
```

### 第 2 步：同步到 origin (AZissue/RVBUST_Code)

在 AICode 推送成功后，从 AICode 同步到 origin：

```bash
# 1. 推送本地 hand-eye-tools 到 origin/hand-eye-tools
git push origin hand-eye-tools

# 2. 验证
git fetch origin
git branch -r | grep hand-eye-tools
```

### 第 3 步：重命名 AICode 分支（可选）

用户希望将 AICode 的 `handeye-calib-tool/tools-panel` 改名为 `HandEyeTools`。

**注意**：GitHub 分支重命名需要具有仓库管理权限的账户操作。

#### 方案 A：通过 GitHub 网页界面（推荐）

1. 在 AICode 仓库的 Branches 页面
2. 找到 `handeye-calib-tool/tools-panel` 分支
3. 点击管理按钮，选择"重命名"
4. 改为 `HandEyeTools`

#### 方案 B：通过 git 命令（本地重命名，需推送权限）

```bash
# 1. 创建本地新分支指向当前的 handeye-calib-tool/tools-panel
git fetch AICode
git checkout -b HandEyeTools AICode/handeye-calib-tool/tools-panel

# 2. 推送新分支到 AICode
git push AICode HandEyeTools

# 3. 删除旧分支（需在 AICode 仓库有权限）
# 在 GitHub 网页上删除 handeye-calib-tool/tools-panel，或通过：
git push AICode :handeye-calib-tool/tools-panel  # 谨慎操作！
```

#### 方案 C：直接在 GitHub 网页上操作（最简单）

1. 访问 https://github.com/keybord317/AICode/branches
2. 在 `handeye-calib-tool/tools-panel` 分支行，点击菜单（...）
3. 选择"重命名分支"
4. 改为 `HandEyeTools`

## 网络问题排查

如果 `git push` 仍然失败（"Failed to connect to server"）：

1. **检查网络连接**：
   ```bash
   Test-NetConnection -ComputerName github.com -Port 443
   ```
   如果 TcpTestSucceeded 为 False，则是网络/防火墙问题。

2. **尝试 SSH 推送**（如果已配置 SSH key）：
   ```bash
   git remote set-url origin git@github.com:AZissue/RVBUST_Code.git
   git remote set-url AICode git@github.com:keybord317/AICode.git
   git push origin hand-eye-tools
   git push AICode hand-eye-tools:handeye-calib-tool/tools-panel
   ```

3. **设置 Git 代理**（如果网络需要代理）：
   ```bash
   git config --global http.proxy [your-proxy-url]
   ```

## 验证清单

推送后，请验证：

- [ ] AICode 的 `handeye-calib-tool/tools-panel`（或改名后的 `HandEyeTools`）包含本次改动
- [ ] origin 的 `hand-eye-tools` 分支已同步
- [ ] 两个仓库的 commit 哈希一致（或形成链路）
- [ ] STATUS.md 交接块中记录已提交

