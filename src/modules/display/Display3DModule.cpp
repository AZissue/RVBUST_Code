#include "Display3DModule.h"

namespace rvc {

void Display3DModule::setDisplayCallback(DisplayCallback cb)
{
    callbackStorage() = std::move(cb);
}

bool Display3DModule::execute(ModuleContext& ctx)
{
    if (!ctx.hasInput("cloud")) {
        ctx.log("no point cloud on input port 'cloud'");
        return false;
    }

    const PointCloud* cloud = ctx.input("cloud").get<PointCloud>();
    if (!cloud || !*cloud || (*cloud)->empty()) {
        ctx.log("input point cloud is null or empty");
        return false;
    }

    // 可选输入：未连接时对应叠加层为空，不视为错误
    DisplayOverlays overlays;
    if (const Plane3D* p = ctx.input("plane").get<Plane3D>())
        overlays.plane = *p;
    if (const Line3D* l = ctx.input("line").get<Line3D>())
        overlays.line = *l;
    if (const Circle3D* c = ctx.input("circle").get<Circle3D>())
        overlays.circle = *c;

    std::string msg = "displaying " + std::to_string((*cloud)->size()) + " points";
    if (overlays.plane) msg += " + plane";
    if (overlays.line) msg += " + line";
    if (overlays.circle) msg += " + circle";
    ctx.log(msg);

    if (auto& cb = callbackStorage())
        cb(getString("viewport"), *cloud, std::move(overlays));
    else
        ctx.log("no display callback registered (headless run?)");

    return true;
}

} // namespace rvc
