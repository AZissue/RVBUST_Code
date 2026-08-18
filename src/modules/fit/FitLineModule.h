#pragma once

// 拟合模块：空间直线拟合（RANSAC，SampleConsensusModelLine）。
// 输入：cloud；参数：distanceThreshold（米）、maxIterations；
// 输出：line（Line3D，方向单位化）、inliers（PointCloud）。

#include "modules/CloudUtils.h"

namespace rvc {

class FitLineModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Fit.Line";

    FitLineModule()
    {
        displayName_ = "直线拟合";
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
        return {{"line", DataType::Line}, {"inliers", DataType::PointCloud}};
    }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
