#pragma once

// 测量模块：圆直径。
// 输入：circle（Circle3D）；输出：diameter（Scalar，米）。

#include "core/ModuleBase.h"

namespace rvc {

class CircleMeasureModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Measure.CircleDiameter";

    CircleMeasureModule() { displayName_ = "圆直径"; }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override { return {{"circle", DataType::Circle}}; }
    std::vector<PortDecl> outputPorts() const override
    {
        return {{"diameter", DataType::Scalar}};
    }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
