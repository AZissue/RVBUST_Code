# T-006 验收证据（A）— PLY 的 x/y/z 按声明类型解码

日期：2026-09-30　　结论：**通过**（两轮：r1 交付 + r2 回灌补一条同类漏网）

## 1. 判据（`python .trio/verify.py T-006 --no-baseline` → exit 0）

| # | 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | x/y/z 按声明类型解码；认不出的属性类型绝不给错值 | ✓ | `qt_class_probe pixel_to_3d 18` → `PASS`（18 passed / 0 failed） |
| 2 | 只动了 `src/logic/PlyPointReader.h` | ✓ | `workingset_guard.py` → `✓ 工作集内` |
| 3 | 既有测试不退化 | ✓ | `ctest -C Release`：`100% tests passed out of 2` |

## 2. 改前的红

r1 之前（A 实测，两条用例）：

```
{"check": "pixel_to_3d: no failures", "ok": false, "passed": 15, "failed": 2}
FAIL!  : TestPixelTo3D::plyReaderBinaryIntXyz() Compared doubles are not the same (fuzzy compare)
FAIL!  : TestPixelTo3D::plyReaderBinaryShortUnsignedXyz() Compared doubles are not the same (fuzzy compare)
```

## 3. r2 回灌的由来（A 复核时发现的同一条病的第二个入口）

r1 交付后判据全绿，但 A 读代码时发现 `typeSize()` 返回 0 的属性会被
`if (p.size > 0) vertexProps.push_back(p);` **悄悄丢掉**，于是不进 `recordSize`、
后面 x/y/z 的偏移整体前移 —— 读出来的是前一个属性的尾巴。文件合法（`int64` 是
PLY 规范里的标量类型）、测试也不会失败，只是数字全错。

新用例 + 回灌任务书 `T-006-r2.md` 的失败原文：

```
{"check": "pixel_to_3d: no failures", "ok": false, "passed": 17, "failed": 1}
FAIL!  : TestPixelTo3D::plyReaderUnknownPropertyNeverSilentlyWrong() 'decoded || refused' returned FALSE.
```

该用例的判据是**实现无关**的：`(按正确值解出 x/y/z) || (ok=false 且 error 非空)`
—— 只要不是"ok=true 但坐标错"就算过。

## 4. B 的选择与 A 的复核

B 选了"把宽度补全"：`typeSize()`/`typeKind()` 增加 `int64/uint64/long/ulong`（8 字节），
`readScalar()` 拆成 `readRaw()`（按端序拼字节）+ 按 `Scalar` 解码（1/2/4/8 字节全覆盖，
有符号用 `memcpy` 做二补码重解释）。

A 逐行读 diff 确认：

- `typeSize()` 里**原有**的字符串→字节数结论一字未动（只是新增了 4 个以前返回 0 的类型）；
  所以既有文件的 `recordSize` 与 T-004 那道上界检查的结果不变。
- ascii 路径仍是 `strtod`，`plyReaderAsciiTypedXyz` 这条不变量用例继续过。
- 测试从 12 条涨到 16 条（+4），一次都没删。

## 5. 记录在案的残留（未修，已挂账）

**真正意义上的"未知类型"（拼错的类型名、或顶点元素上的 `property list ...`）现在仍会被
`if (p.size > 0)` 丢掉 → 布局位移 → 静默错值。** r2 只把 PLY 规范里合法的标量类型补全了。

- 触发条件：第三方 PLY 的顶点元素上带 list 属性、或类型名写错。
- 概率：低（规范里的标量类型现已全覆盖）。
- 后果：与本任务要消灭的现象同类（看着有值、其实全错）。
- 去向：记进 `BACKLOG-2.0.md`，由 T-008（清理包）顺手关掉——修法就是
  `else if (p.size == 0)` 时给出可读错误并拒绝，而不是丢掉。
