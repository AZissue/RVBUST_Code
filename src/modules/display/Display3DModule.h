#pragma once

// 显示类模块：3D 点云 + 几何图形叠加显示。
// 输入：cloud（必需）+ plane / line / circle（可选，允许未连接）。
// 解耦设计：模块不依赖任何 QWidget，渲染回调由 UI 层（或无头自测）注入。

#include <functional>
#include <optional>

#include "core/ModuleBase.h"

namespace rvc {

// 可选的几何叠加层（未连接的输入对应为空）
struct DisplayOverlays {
    std::optional<Plane3D>  plane;
    std::optional<Line3D>   line;
    std::optional<Circle3D> circle;
};

class Display3DModule : public ModuleBase {
public:
    static constexpr const char* kTypeId = "Display.Display3D";

    // 显示回调：参数为目标视窗名（模块 viewport 参数）+ 点云 + 叠加层。
    // 由 UI 层路由器注入，按名分发到对应视窗 Dock。
    using DisplayCallback =
        std::function<void(const std::string& viewport, PointCloud, DisplayOverlays)>;

    Display3DModule()
    {
        displayName_ = "3D显示";
        // 目标视窗名；不存在的视窗由 UI 层自动创建
        declareParam({"viewport", ParamType::String, std::string("主视窗")});
    }

    std::string typeId() const override { return kTypeId; }

    std::vector<PortDecl> inputPorts() const override
    {
        return {{"cloud", DataType::PointCloud},
                {"plane", DataType::Plane, /*optional=*/true},
                {"line", DataType::Line, /*optional=*/true},
                {"circle", DataType::Circle, /*optional=*/true}};
    }
    std::vector<PortDecl> outputPorts() const override { return {}; }

    bool execute(ModuleContext& ctx) override;

    // 注入显示回调（进程级，UI 层启动时设置；无头自测可注入计数断言）。
    // 之后创建的所有实例 execute 时都会调用该回调。
    static void setDisplayCallback(DisplayCallback cb);

private:
    static DisplayCallback& callbackStorage()
    {
        static DisplayCallback cb;
        return cb;
    }
};

} // namespace rvc
