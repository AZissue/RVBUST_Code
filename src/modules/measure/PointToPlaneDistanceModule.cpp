#include "PointToPlaneDistanceModule.h"

#include <cmath>

#include "modules/CloudUtils.h"

namespace rvc {

bool PointToPlaneDistanceModule::execute(ModuleContext& ctx)
{
    const PointCloud* cloudIn = ctx.input("cloud").get<PointCloud>();
    const Plane3D* plane = ctx.input("plane").get<Plane3D>();
    if (!cloudIn || !*cloudIn || (*cloudIn)->empty()) {
        ctx.log("no point cloud on input port 'cloud'");
        return false;
    }
    if (!plane) {
        ctx.log("no plane on input port 'plane'");
        return false;
    }

    // ROI：连线 roi > 自有参数 > 不裁；拟合/测量模块强制要求 ROI
    const RoiBox roi = resolveRoi(ctx, *this);
    if (!roi.valid) {
        ctx.log("ROI not set. Link an roi input or enable the module's own ROI parameters.");
        return false;
    }
    const PointCloud dense = removeNaNIfNeeded(cropByRoi(*cloudIn, roi));
    if (dense->empty()) {
        ctx.log("input point cloud is empty after ROI/NaN removal");
        return false;
    }

    double sum = 0.0, maxDist = 0.0;
    for (const auto& p : dense->points) {
        const double dist = std::fabs(static_cast<double>(plane->signedDistance(p.x, p.y, p.z)));
        sum += dist;
        maxDist = std::max(maxDist, dist);
    }
    const double mean = sum / static_cast<double>(dense->size());

    ctx.log("point-to-plane distance over " + std::to_string(dense->size()) +
            " points: mean " + std::to_string(mean) + " m, max " + std::to_string(maxDist) + " m");

    ctx.setOutput("mean", makePortValue(DataType::Scalar, mean));
    ctx.setOutput("max", makePortValue(DataType::Scalar, maxDist));
    return true;
}

} // namespace rvc
