#pragma once

// 拟合模块：空间圆拟合（RANSAC，SampleConsensusModelCircle3D）。
// 输入：cloud；参数：distanceThreshold（米）、maxIterations、radiusMin/radiusMax（米）；
// 输出：circle（Circle3D）、inliers（PointCloud）。
// PCL 1.13 系数含义：[cx, cy, cz, radius, nx, ny, nz]。

#include "modules/CloudUtils.h"

namespace rvc {

class FitCircleModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Fit.Circle";

    FitCircleModule()
    {
        displayName_ = "圆拟合";
        declareParam({"distanceThreshold", ParamType::Double, 0.005, 1e-6, 1.0});
        declareParam({"maxIterations", ParamType::Int, 10000, 1, 10000000});
        declareParam({"radiusMin", ParamType::Double, 0.001, 1e-6, 1e3});
        declareParam({"radiusMax", ParamType::Double, 1.0, 1e-6, 1e3});
        declareRoiParams(*this);
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override
    {
        return {{"cloud", DataType::PointCloud}, {"roi", DataType::Roi, /*optional=*/true}};
    }
    std::vector<PortDecl> outputPorts() const override
    {
        return {{"circle", DataType::Circle}, {"inliers", DataType::PointCloud}};
    }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
