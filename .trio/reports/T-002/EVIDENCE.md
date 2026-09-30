# T-002 验收证据索引（A，2026-09-30）

## 结论

| 判据 | 结论 | 证据 |
|---|---|---|
| 1 3D 视窗里不再有那条提示（且进日志） | 通过 | `reports/T-002/probe_pickhint.py` exit 0（改前 `in_view=1`、控件 left=976 vs 日志列 1254；改后 `in_view=0`） |
| 2 回归：工具面板 15 项逐项选中不崩 | 通过 | `reports/T-003/repro_crash.py` exit 0 |
| 3 回归：连相机后预览/拍照不崩 | 通过 | `reports/T-002/repro_camera_crash.py` exit 0（预览/拍照各存活 12 s） |
| 4 既有 ctest 全过 | 通过 | `ctest`：100% tests passed out of 2 |
| 5 工作集不越界 | 通过 | `reports/T-003/workingset_guard.py` exit 0（只动 src/ui/ 4 个文件 + src/app/MainWindow.cpp 一个连接） |
| 6 观感（人眼判） | 见下 | 截图 |

## 判据 6 逐项

- **2D 视窗描边去掉**：通过。`reports/T-002/zz_2d_bl_corner.png`（改后）与
  `reports/T-001/zoom_2d_bl_corner.png`（改前）对比，改前左边与下边各有一条 2px 灰线（
  `Image2DView.cpp:139` 的 `border: 2px solid #D9D9D9`），改后没有了。
- **按钮圆角 8px**：通过。改后「图像」是明显的胶囊形（`zz_2d_bl_corner.png`）；
  `Theme::viewOverlayButtonStyle()/viewOverlayLabelStyle()` 与 `kGlassRadius` 三处都改成 8。
- **3D 按钮与 2D 同一套观感**：通过。`reports/T-002/zz_3d_toolbar.png` 里三个按钮是
  圆角半透明胶囊。数值核对（`cam_08_capture_alive.png` 采样）：
  胶囊内 `(57,62,75)` vs 旁边场景底色 `(25,31,46)`；
  按白 14% 合成算 `25/31/46 ×0.86 + 255×0.14 = 57.2 / 62.4 / 75.3` —— **与实测逐通道吻合**，
  说明 3D 侧就是任务书要求的 `alpha = 0.14`（原恒定底 0.20 × 0.7）。
- **2D 按钮底"再透 30%"**：按实现确认（`GlassOverlay::paintEvent` 里
  `p.setOpacity(0.70)` 只作用在模糊底那一层，文字/QSS 层仍是 1.0），**今天没能再拍一张
  可视对比**：2D 视窗四角是黑边（4:3 画面配近似方形视窗，标签与工具栏正好落在黑边上），
  而当前相机取景的上半部也是黑的，模糊层在黑底上本来就看不出来。改前的可视证据是
  `reports/T-001/zoom_live_title2.png`（"2D 实时图像"底下的椒盐噪点被抹平）——那是模糊层
  存在性的证明；30% 的差值请人在现场用有纹理的画面顺眼复核。

## 顺带复核（回归）

- 离线「像素→3D」端到端仍然出值：点冻结画面得到 `-18.499, -9.483, 388.268` mm
  （`reports/T-001/probe_glass.log`）。
- `.pair/tools/ui_check_012.py`（第 12 回合的设置/工具窗口回归）在 T-001 那轮已全过，
  本轮未触及那两个窗口，未重跑。
