#pragma once

// 预处理模块：体素降采样。
// 输入：cloud；参数：leafSize（体素边长，米）；输出：cloud。

#include "core/ModuleBase.h"

namespace rvc {

class VoxelDownsampleModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Preprocess.VoxelDownsample";

    VoxelDownsampleModule()
    {
        displayName_ = "体素降采样";
        declareParam({"leafSize", ParamType::Double, 0.002, 1e-6, 1.0});
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override { return {{"cloud", DataType::PointCloud}}; }
    std::vector<PortDecl> outputPorts() const override { return {{"cloud", DataType::PointCloud}}; }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
