#pragma once

// 测量模块：两面夹角 / 平行面间距。
// 输入：planeA + planeB；
// 输出：angle（Scalar，度，始终输出）；
//       distance（Scalar，米，仅夹角 < parallelAngleDeg 时输出，否则不给值并 log 提示）。

#include "core/ModuleBase.h"

namespace rvc {

class PlaneToPlaneModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Measure.PlaneToPlane";

    PlaneToPlaneModule()
    {
        displayName_ = "面面夹角/间距";
        declareParam({"parallelAngleDeg", ParamType::Double, 5.0, 0.0, 45.0});
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override
    {
        return {{"planeA", DataType::Plane}, {"planeB", DataType::Plane}};
    }
    std::vector<PortDecl> outputPorts() const override
    {
        return {{"angle", DataType::Scalar}, {"distance", DataType::Scalar}};
    }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
