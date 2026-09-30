# 相机「预览/拍照闪退」的二分定位（A，2026-09-29）

人的原话：「在我连接相机之后再点击预览或者拍照会导致程序闪退」。
相机：RVC-I2120，SN `I1GM112B652`（真机，插在本机）。

探针：`reports/T-002/repro_camera_crash.py`（连真机 → 选 SN → 确定 → 点预览 → 点拍照，
每步盯着 `Popen.poll()`）。两个 exe 跑同一份探针：

| 构建 | 改动 | 结果 |
|---|---|---|
| **B 的 T-001 交付**（`src/ui/` 5 个文件已改） | Theme 去底色 + 2D GlassOverlay + 3D DWM accent + ToolsPanel 单滚动区 | 连上 OK；**点「预览」后 ~1.0 秒进程死，`exit_code=3221225477`（0xC0000005 ACCESS_VIOLATION）** |
| **HEAD 原样**（`git stash push -- src/ui/...` 后重新编译） | 无 | 连上 OK；预览存活 12 秒；拍照存活 12 秒；`NOT REPRODUCED` |

原始输出：

- B 版：`reports/T-002/repro_camera_crash.log`（`probe_exit=1`）
- HEAD 版：同一条探针，`预览 存活 12 秒` / `拍照 存活 12 秒` / `NOT REPRODUCED (alive)`，
  截图 `reports/T-002/cam_06_preview_alive.png`、`cam_08_capture_alive.png`
  （注意这两张已被 B 版的重跑覆盖，结论以本节表格为准——重跑一次即可复现）

结论：**这是 T-001 引入的回归，不是现场原有缺陷**。相机没连上时 2D 视窗没有画面，
那条"铺背后模糊底"的绘制路径一次都没跑过；一接上真相机、预览开始出帧，
`render()` → `updateOverlayBackdrops()` → `GlassOverlay::paintEvent` →
`Image2DView::overlayBlurUnder()` 就第一次真正执行，随即访问违例。

顺带说明它为什么**必须**在下一轮修掉：人给的第一条就是"闪退"，
而这一条把"连相机→预览"这条主链路整个打断了——比原来那个"点某个工具页才崩"更严重。
