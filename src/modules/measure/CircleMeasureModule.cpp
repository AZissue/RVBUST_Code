#include "CircleMeasureModule.h"

namespace rvc {

bool CircleMeasureModule::execute(ModuleContext& ctx)
{
    const Circle3D* circle = ctx.input("circle").get<Circle3D>();
    if (!circle || circle->radius <= 0.0f) {
        ctx.log("no valid circle on input port 'circle'");
        return false;
    }

    const double diameter = 2.0 * static_cast<double>(circle->radius);
    ctx.log("circle diameter: " + std::to_string(diameter) + " m");

    ctx.setOutput("diameter", makePortValue(DataType::Scalar, diameter));
    return true;
}

} // namespace rvc
