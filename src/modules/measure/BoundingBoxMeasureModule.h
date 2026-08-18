#pragma once

// 测量模块：点云包围盒尺寸（pcl::getMinMax3D）。
// 输入：cloud + roi（可选）；输出：sizeX / sizeY / sizeZ（Scalar，米）。

#include "modules/CloudUtils.h"

namespace rvc {

class BoundingBoxMeasureModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Measure.BoundingBox";

    BoundingBoxMeasureModule()
    {
        displayName_ = "包围盒尺寸";
        declareRoiParams(*this);
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override
    {
        return {{"cloud", DataType::PointCloud}, {"roi", DataType::Roi, /*optional=*/true}};
    }
    std::vector<PortDecl> outputPorts() const override
    {
        return {{"sizeX", DataType::Scalar}, {"sizeY", DataType::Scalar}, {"sizeZ", DataType::Scalar}};
    }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc

