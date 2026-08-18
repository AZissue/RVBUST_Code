#pragma once

// 预处理模块：统计离群点去除。
// 输入：cloud；参数：meanK（邻域点数）、stddevMul（标准差倍数）；输出：cloud。

#include "core/ModuleBase.h"

namespace rvc {

class StatisticalDenoiseModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Preprocess.StatisticalDenoise";

    StatisticalDenoiseModule()
    {
        displayName_ = "统计去噪";
        declareParam({"meanK", ParamType::Int, 50, 1, 10000});
        declareParam({"stddevMul", ParamType::Double, 1.0, 0.0, 100.0});
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override { return {{"cloud", DataType::PointCloud}}; }
    std::vector<PortDecl> outputPorts() const override { return {{"cloud", DataType::PointCloud}}; }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
