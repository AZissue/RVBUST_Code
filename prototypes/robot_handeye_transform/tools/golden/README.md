# tools/golden —— 独立验证参照物（不参与生产代码，勿改）

本目录是 @verify 交付的**参照实现与原始测量数据**，用途有二：

1. `tests/test_order_detect.py` 的**内核等价性**基准（引用本目录，不复制内容）；
2. 排出方案/KB 里引用过的每一个数字的**原始出处**（谁跑的、跑了什么、结论是什么）。

**纪律**：本目录内容**只增不改**。改了就作废了它作为"原结论出处"的效力。
任何文件被移动/改名，等于 dev 的等价性测试与 KB 引用同时失据 —— 要动先跟 @verify 说。

## 文件清单与出处

| 文件 | 是什么 | 它产生过哪条结论 |
|---|---|---|
| `full_handeye.py` | 12 参数 6DOF 手眼拟合内核（多起点 LM，逐记录残差），函数 `resid(p, Tgb, Ttc)`。**内核等价性测试的参照实现** | ①「12 候选下真值唯一：rms=0 vs 次佳 148~150」；②「n=2/3/4/5 均仅真值通过」；③「退化(全绕Z) 12→4/12」(见 r14_candidates.py 的 24 常量版) |
| `min_poses.py` | 位姿数与退化激励的边界用例（全枚举 12 分支 + 最小二乘） | 「n=2 唯一的反例：全绕 Z 时 4/12 同时通过」；「Z+±3°Y 激励补足后回到 1/12」 |
| `r14_candidates.py` | R14 三项 spike（合成真值 oracle）：18/24 候选唯一性、proper Euler 真值、rad 按 deg 解析 | 「一般位姿 n=8：12→1/12、18→1/18、24→1/24，次佳 148~150」；「真值=PE → 0 通过（fail-closed）」；「rad 数据按 deg 解析 → 0 通过；48 分支唯一命中 (XYZ, rad)」；「退化：12→4/12、18→6/18、24→8/24」 |
| `sec1.py` | 只跑 r14 的候选集口径一节（快速复跑） | 同上第一条的复核（`sec1_out.txt` 未随更，数字见上） |
| `sdk_sweep_v2.py` | **真实数据** SDK sweep：24 分支 × poseType=3 → `totalMeanError` 排名 + 噪声底 σ + 阈值建议 | 「真值 = `xyz`/deg，tme=2.051628；次佳 ZYX/deg=80.398 → 39.2×」；「LOO σ=0.0642、子集 σ=0.1110 → pass_tol=0.333」；「`autoRemoveLargeErrorData=true` 会让错约定 yxz/deg 刷到 1.422(仅 10/27 组) 压过真值 —— 必须用 false」 |
| `sdk_loo.py` | 留一稳定性实测（前 3 名候选 × 27 次剔除） | 「冠军翻转 0/27」；「倍数差在 2/27 掩码掉到 9.77×/9.98× → 倍数差只用全量判、留一只断言冠军不变」 |
| `sdk_sweep_v2.json` | 上面 sweep 的全量原始结果（24 分支 tme + 27 组逐条误差 + LOO/子集样本） | 上表两行的原始数据 |
| `sweep2_out.txt` / `loo_out.txt` | 控制台原始输出（未经整理，防止我转述失真） | 同上 |

## 复现入口

```bash
# 合成侧（uv 隔离环境，注意先 unset PYTHONPATH）
unset PYTHONPATH && uv run --no-project --with numpy --with scipy --python 3.12 python r14_candidates.py
# 真实数据 SDK sweep（需要手眼标定软件 v3.9.0 在 E:/jingz/Desktop，及 C++ 测试数据集）
unset PYTHONPATH && uv run --no-project --with numpy --with scipy --python 3.12 python sdk_sweep_v2.py
```

`sdk_sweep_v2.py` / `sdk_loo.py` **自己写 ctypes 绑定**（按 `HandEye.h` 重写，非复用 `hand-eye-tools/handeye_sdk.py`）——
两条独立实现都保留、不合并，互为印证。二者会在数据集目录临时写入候选位姿文件并自行清理（运行后可 `ls` 复核无残留）。

## 已知限制（引用数字时必须一起说）

- 合成侧全部数字来自**无噪**数据，`pass_tol=0.05` 是合成口径；现场口径见 `sdk_sweep_v2.py` 的 `max(0.05, 3σ)`。
- `r14_candidates.py` 的"退化通过数 4/12、6/18、8/24"是**纯拟合排名**口径（没有激励门）；6B-1 新内核在同样数据上走**激励门**先判 `INSUFFICIENT`、`ranking=[]`，两者不是同一个口径，不能互相引用。
- 真实数据集 `D:/RVC_SRC/Cpp/HandEyeCalibration_Test/build/data/marker` 是 **eye-to-hand、markerType=0（标定板）、点云单位米、位姿单位毫米**。

## 不在本目录的探针

A10 矩阵文件的独立边界探针（v1 18 项 / v2 32 项）仍在 @verify 的 scratch：`a10_boundary_probe.py`、`a10_probe_v2.py`（含 null fail-open、verification 自洽、相似键拒收等实测）。需要长期保存请说一声，挪到 `tools/verify_probes/`。
