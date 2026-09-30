# T-004 验收证据（A）— PLY 坏头部不再带走进程

日期：2026-09-30　　结论：**通过**　　提交：见本轮 commit

## 1. 判据（`python .trio/verify.py T-004 --no-baseline` → exit 0）

| # | 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | 坏头部报错返回、进程存活 | ✓ | `reports/T-004/ply_probe.py` → `{"result": "PASS"}`；`.trio/reports/t004/verify.json` |
| 2 | 工作集守门：只动了 `src/logic/PlyPointReader.h` | ✓ | `reports/T-004/workingset_guard.py` |
| 3 | 既有测试不退化 | ✓ | `ctest -C Release`：`100% tests passed out of 2`（unit_tests / measurement_truth） |

## 2. 改前的红（发任务书之前，`--pre` 全红）

```
{"check": "unit_tests exited without being killed", "ok": false, "exit_code": 3765269347}
{"check": "pixel_to_3d: no failures", "ok": false, "passed": 11, "failed": 1}
{"result": "FAIL", "failures": ["FAIL!  : TestPixelTo3D::plyReaderRejectsOversizedVertexCount() Caught unhandled exception"]}
```

`exit_code 3765269347` = `0xE06D7363`（MSVC 未捕获 C++ 异常）—— 就是 `std::bad_alloc`。
完整原文：`reports/T-004/pre_red.log`。

## 3. 改后的绿

```
{"check": "unit_tests exited without being killed", "ok": true, "exit_code": 0}
{"check": "pixel_to_3d: no failures", "ok": true, "passed": 14, "failed": 0}
{"result": "PASS"}
```

14 = 12 条用例 + `initTestCase` + `cleanupTestCase`；两条新用例逐条确认跑到了：

```
PASS   : TestPixelTo3D::plyReaderRejectsOversizedVertexCount()
PASS   : TestPixelTo3D::plyReaderRejectsShortBinaryWithBigClaim()
Totals: 14 passed, 0 failed, 0 skipped, 0 blacklisted, 13ms
```

## 4. A 独立复核的要点（不采信 B 的自述）

- `git diff -- src/logic/PlyPointReader.h` 只多了一段：头解析之后、`reserve()` 之前，
  用 `remainingBytes / minBytesPerVertex` 做**除法**比较（不溢出），bin 取 `recordSize`、
  ascii 取 `vertexProps.size()`（每顶点至少这么多个 token、每 token 至少 1 字节）——
  是**下界**，只会漏判不会误杀；`bodyStart < 0`（tellg 失败）也走拒绝。
- 既有 10 条 PLY 用例（ascii / binary_float / face-first / 坏头 / 缺 xyz）全过 → 好文件路径没动。
- 探针的 PASS 依赖四件事同时成立：进程退出码 0/1、类报告写出、`failed == 0`、`passed ≥ 12`。

## 5. 遗留

- ascii 用的是 token 数下界（不逐行精确），属有意保守：极端"token 极短"的坏文件仍可能漏判，
  但漏判的后果只是回到旧行为（读时才发现不足）——不崩。
- `verify.py` 的基线通道在本仓不适用（见 `.trio/tasks/T-004.checks.py` 顶部说明），
  已在 T-008 里挂账。
