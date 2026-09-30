# T-005 验收证据（A）— 保存路径的"假成功"与备份原子性

日期：2026-09-30　　结论：**通过**（含一条 B 主动声明的语义偏离，A 判定可接受）

## 1. 判据（`python .trio/verify.py T-005 --no-baseline` → exit 0）

| # | 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | 导出失败上报 + 界面不假成功 + 备份带版本/恢复跳过损坏文件 | ✓ | `python reports/tools/qt_class_probe.py save_export 8` → `{"result":"PASS"}`（8 passed / 0 failed） |
| 2 | 工作集守门 | ✓ | `python reports/tools/workingset_guard.py src/logic/DataManager.h src/logic/DataManager.cpp src/logic/CaptureFlow.h src/logic/CaptureFlow.cpp` → `✓ 工作集内` |
| 3 | 既有测试不退化 | ✓ | `ctest -C Release`：`100% tests passed out of 2` |

## 2. 改前的红（`--pre`）

```
✗ [判据 1] 导出失败被上报 + 界面不假成功 + 备份带版本/恢复跳过损坏文件
✓ [判据 2] 工作集守门
✓ [判据 3] 既有测试不退化
✓ 3 条断言全红（red 的都红、green 的都绿）——可以发任务书了
```

判据 1 的红是**编译级**的：`tests/test_save_export.cpp` 调用还不存在的
`DataManager::lastExportError()`，新用例编不出来 → 报告里没有 `save_export` 这一类。

## 3. A 独立复核的要点

真机意义上的"人能看到的"效果由 6 条用例分别钉住（都在 `tests/test_save_export.cpp`）：

- 让导出失败的手法是可复现的：在会话目录里放一个**名为 `pose.txt` 的目录** ——
  `QSaveFile` 无法把它替换成文件，于是只有 marker 导出这一步坏掉；
- `writeHandEyeOutput()==false` 且 `lastExportError()` 含 `pose.txt`；
- 正常路径不回归：`true` + 错误为空 + `pose.txt` 内容与记录逐行一致；
- `CaptureFlow::save()`：不发 `success=true` 的 toast，发一条含 `pose.txt` 的
  `success=false` toast + 一条 `level=="error"` 的 `logRequested`，且记录照常留下（`count()==1`）；
- `undo()` 同理，且撤销后 `count()==0`；
- 备份 `version==1`、本身是合法 JSON；两个候选（老的完好 / 新的截断）里
  `findLatestBackup()` 返回**完好那个**。

A 逐行读了 `git diff`：改动只落在 3 个源文件 + 测试登记，`writeMarkerOutput/writeTcpOutput`
由 `void` 改 `bool`（private，允许），失败信息带文件名，`writeBackupNow()` 用 `QSaveFile`，
`findLatestBackup()` 先验内容再比 mtime。

## 4. 记录在案的偏离（A 判定：可接受，理由如下）

B 把 `writeHandEyeOutput()` 的**空记录行为**改了：原来 `m_records.empty()` 直接
`return false`（什么都不写），现在零记录也重写导出文件（失败时返回 false）。

- 为什么必须动：撤销到零记录时，原来"直接 return false + 错误为空"没法区分
  "没数据"和"写失败"，界面只能沉默；改完之后失败才有可读原因。
- 为什么可接受：唯一的两个调用点（`CaptureFlow::save/undo`）都在**加/删记录之后**调用，
  不依赖旧语义；`tests/` 里没有任何断言依赖它（ctest 2/2 全过）。
- 顺带的好处：撤销掉最后一条记录后，磁盘上不再留着一个**过期的** pose.txt。
- 签名冻结项（`bool writeHandEyeOutput()` 不加参数）与其余公开方法签名**未动**。

## 5. 遗留

- 失败 toast 的文案是「第 N 组数据保存失败: 写入 pose.txt 失败: …」。记录其实已经落盘，
  严格说"保存失败"偏重；但它明确指出了失败的文件，比"保存成功"有用得多。人不满意可以在
  T-013 的界面参数化里一并调整文案。
