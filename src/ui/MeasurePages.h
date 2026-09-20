#pragma once

// ── 8 个测量方法页（第 7 回合 P3）──────────────────────────────────────
//
// 每个方法一个 QWidget 子类，共用 MeasurePage 基类里的 ROI / 结果表 / 重复性
// 序列 / 快照发布；子类只写 compute()——它自己的算法、自己那几行结果、自己的
// 显示载荷。列表顺序与 MeasureTools::methodSpecs() 一致（也就是 Method 枚举）。
#include <vector>

#include "ui/MeasurePage.h"

namespace MeasurePages {

// 左侧工具列表里的 8 个条目，按 methodSpecs() 的顺序建好。
std::vector<MeasurePage*> createAll(QWidget* parent);

MeasurePage* create(MeasureTools::Method method, QWidget* parent);

} // namespace MeasurePages
