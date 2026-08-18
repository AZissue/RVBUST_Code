#include "PlaneToPlaneModule.h"

#include <cmath>

namespace rvc {

namespace {
constexpr double kPi = 3.14159265358979323846;
}

bool PlaneToPlaneModule::execute(ModuleContext& ctx)
{
    const Plane3D* pa = ctx.input("planeA").get<Plane3D>();
    const Plane3D* pb = ctx.input("planeB").get<Plane3D>();
    if (!pa || !pb) {
        ctx.log("missing input plane (planeA / planeB)");
        return false;
    }

    // 无向夹角：法线点积取绝对值
    double dot = static_cast<double>(pa->a) * pb->a + static_cast<double>(pa->b) * pb->b +
                 static_cast<double>(pa->c) * pb->c;
    dot = std::clamp(dot, -1.0, 1.0);
    const double angleDeg = std::acos(std::fabs(dot)) * 180.0 / kPi;

    ctx.log("plane-to-plane angle: " + std::to_string(angleDeg) + " deg");
    ctx.setOutput("angle", makePortValue(DataType::Scalar, angleDeg));

    const double threshold = getDouble("parallelAngleDeg");
    if (angleDeg < threshold) {
        // 近平行：对齐法线方向后 |d1 - d2| 即间距
        Plane3D aligned = *pb;
        aligned.alignWith(Eigen::Vector3f(pa->a, pa->b, pa->c));
        const double distance =
            std::fabs(static_cast<double>(pa->d) - static_cast<double>(aligned.d));
        ctx.log("parallel planes distance: " + std::to_string(distance) + " m");
        ctx.setOutput("distance", makePortValue(DataType::Scalar, distance));
    } else {
        ctx.log("planes are not parallel (angle >= " + std::to_string(threshold) +
                " deg), distance output not set");
    }
    return true;
}

} // namespace rvc
