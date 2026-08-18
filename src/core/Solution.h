#pragma once

// 方案（Solution）：持有一个 Process，负责 JSON 保存/加载。
// 方案保存以 core JSON 为准（模块 + 参数 + 连线 + 节点位置）。

#include <memory>
#include <QString>

#include "Process.h"

namespace rvc {

class Solution {
public:
    Solution() : process_(std::make_unique<Process>()) {}

    Process& process() { return *process_; }
    const Process& process() const { return *process_; }

    // 保存到 JSON 文件；失败返回 false 并填 err
    bool save(const QString& filePath, QString* err = nullptr) const;

    // 从 JSON 文件加载（清空当前流程后重建）；失败返回 false 并填 err
    bool load(const QString& filePath, QString* err = nullptr);

private:
    std::unique_ptr<Process> process_;
};

} // namespace rvc
