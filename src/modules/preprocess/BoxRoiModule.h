#pragma once

// 预处理模块：盒式 ROI 裁剪（三轴范围）。
// 输入：cloud；参数：xmin/xmax/ymin/ymax/zmin/zmax（米，默认 ±1e9 表示不裁）；
// 输出：cloud（裁剪后点云）、roi（当前 ROI 参数导出为 RoiBox，供下游模块订阅）。

#include "core/ModuleBase.h"

namespace rvc {

class BoxRoiModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Preprocess.BoxRoi";

    BoxRoiModule()
    {
        displayName_ = "ROI裁剪";
        declareParam({"xmin", ParamType::Double, -1e9});
        declareParam({"xmax", ParamType::Double, 1e9});
        declareParam({"ymin", ParamType::Double, -1e9});
        declareParam({"ymax", ParamType::Double, 1e9});
        declareParam({"zmin", ParamType::Double, -1e9});
        declareParam({"zmax", ParamType::Double, 1e9});
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override { return {{"cloud", DataType::PointCloud}}; }
    std::vector<PortDecl> outputPorts() const override
    {
        return {{"cloud", DataType::PointCloud}, {"roi", DataType::Roi}};
    }

    bool execute(ModuleContext& ctx) override;
};

} // namespace rvc
