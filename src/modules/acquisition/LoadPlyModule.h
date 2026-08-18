#pragma once

// 采集类模块：从 PLY 文件加载点云。
// 参数：filePath（FilePath）；输出：cloud（PointCloud）。

#include "core/ModuleBase.h"

namespace rvc {

class LoadPlyModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Acquisition.LoadPly";

    LoadPlyModule()
    {
        displayName_ = "加载PLY点云";
        declareParam({"filePath", ParamType::FilePath, std::string{}});
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override { return {}; }
    std::vector<PortDecl> outputPorts() const override { return {{"cloud", DataType::PointCloud}}; }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
