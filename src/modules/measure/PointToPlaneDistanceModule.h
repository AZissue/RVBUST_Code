#pragma once

// 测量模块：点云到平面的距离统计。
// 输入：cloud + plane + roi（可选）；输出：mean / max（Scalar，米）。

#include "modules/CloudUtils.h"

namespace rvc {

class PointToPlaneDistanceModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Measure.PointToPlaneDistance";

    PointToPlaneDistanceModule()
    {
        displayName_ = "点面距离";
        declareRoiParams(*this);
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override
    {
        return {{"cloud", DataType::PointCloud},
                {"plane", DataType::Plane},
                {"roi", DataType::Roi, /*optional=*/true}};
    }
    std::vector<PortDecl> outputPorts() const override
    {
        return {{"mean", DataType::Scalar}, {"max", DataType::Scalar}};
    }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
