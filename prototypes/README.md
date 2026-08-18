# prototypes — 功能原型与单元测试

> 位置：`D:\RVC_SRC\Python\MultiCameraCalibration\prototypes`

本目录用于存放各子功能的**独立原型**和**单元测试**。每个子功能一个子文件夹，内部自包含 `core/`（核心算法）、`app/`（可运行 UI/脚本）、`tests/`（单元测试），验证稳定后再合并到主项目 `src/` 中。

---

## 目录结构

```
prototypes/
├── README.md                          # 本文件
├── turntable_360_stitch/              # 转台 360° 拼接
│   ├── core/
│   │   └── turntable_calibrator.py
│   ├── app/
│   │   └── simple_ui.py
│   ├── tests/
│   │   └── test_synthetic.py
│   └── README.md
├── marker_matching/                   # 标记点匹配（预留）
├── handeye_calibration/               # 手眼标定（预留）
└── ...
```

## 使用原则

1. **子功能隔离**：每个原型独立运行，不依赖其他原型。
2. **先测试后合并**：`tests/` 中通过单元测试后，再把 `core/` 中的稳定算法迁入 `src/core/`。
3. **不修改主项目**：原型阶段不改动 `src/` 下主程序代码，避免影响主分支。
4. **可复用主项目模块**：原型可以通过相对路径引入 `src/core/`、`src/ui/` 等已有模块。

## 当前原型

| 子文件夹 | 功能 | 状态 |
|---|---|---|
| `turntable_360_stitch/` | 相机固定 + 转台旋转 → 角度标定 → 360° 点云拼接 | 开发中，已可实机测试 |

---

## 新增子功能流程

1. 在 `prototypes/` 下新建子文件夹，如 `my_feature/`。
2. 内部创建 `core/`、`app/`、`tests/`。
3. 在 `tests/` 中写单元测试，无硬件时也能验证核心逻辑。
4. 在 `app/` 中写简单 UI 或命令行脚本，方便实机调试验证。
5. 测试稳定后，把 `core/` 中算法迁入 `src/core/`，UI 逻辑参考后合并入主 UI。
