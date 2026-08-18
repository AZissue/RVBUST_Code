#pragma once

// 拟合模块：平面拟合（RANSAC）。
// 输入：cloud；参数：distanceThreshold（米）、maxIterations；
// 输出：plane（Plane3D，法线单位化且与 +Z 半空间对齐）、inliers（PointCloud）。

#include "modules/CloudUtils.h"

namespace rvc {

class FitPlaneModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Fit.Plane";

    FitPlaneModule()
    {
        displayName_ = "平面拟合";
        declareParam({"distanceThreshold", ParamType::Double, 0.005, 1e-6, 1.0});
        declareParam({"maxIterations", ParamType::Int, 1000, 1, 1000000});
        declareRoiParams(*this);
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override
    {
        return {{"cloud", DataType::PointCloud}, {"roi", DataType::Roi, /*optional=*/true}};
    }
    std::vector<PortDecl> outputPorts() const override
    {
        return {{"plane", DataType::Plane}, {"inliers", DataType::PointCloud}};
    }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
