#pragma once

// IO 模块：保存点云为二进制 PLY。
// 输入：cloud；参数：filePath（FilePath）。
// 中文路径规避（RVC 已知陷阱同款）：含非 ASCII 字符时先存 ASCII 临时文件再移动。

#include "core/ModuleBase.h"

namespace rvc {

class SavePlyModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "IO.SavePly";

    SavePlyModule()
    {
        displayName_ = "保存PLY点云";
        declareParam({"filePath", ParamType::FilePath, std::string{}});
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override { return {{"cloud", DataType::PointCloud}}; }
    std::vector<PortDecl> outputPorts() const override { return {}; }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
