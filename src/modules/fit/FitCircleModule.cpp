#include "FitCircleModule.h"

#include "FitUtils.h"
#include "modules/CloudUtils.h"

namespace rvc {

bool FitCircleModule::execute(ModuleContext& ctx)
{
    const PointCloud* cloudIn = ctx.input("cloud").get<PointCloud>();
    if (!cloudIn || !*cloudIn) {
        ctx.log("no point cloud on input port 'cloud'");
        return false;
    }

    // ROI：连线 roi > 自有参数 > 不裁；拟合/测量模块强制要求 ROI
    const RoiBox roi = resolveRoi(ctx, *this);
    if (!roi.valid) {
        ctx.log("ROI not set. Link an roi input or enable the module's own ROI parameters.");
        return false;
    }
    const PointCloud fitted = cropByRoi(*cloudIn, roi);
    if (roi.valid)
        ctx.log("fitting within ROI, " + std::to_string((*cloudIn)->size()) + " -> " +
                std::to_string(fitted->size()) + " points");
    if (fitted->empty()) {
        ctx.log("no points inside ROI");
        return false;
    }

    RansacResult res = ransacFit(fitted, pcl::SACMODEL_CIRCLE3D,
                                 getDouble("distanceThreshold"), getInt("maxIterations"),
                                 getDouble("radiusMin"), getDouble("radiusMax"));
    if (!res.ok) {
        ctx.log(res.error);
        return false;
    }

    // PCL 1.13 系数：[cx, cy, cz, radius, nx, ny, nz]
    Circle3D circle;
    circle.center =
        Eigen::Vector3f(res.coeffs.values[0], res.coeffs.values[1], res.coeffs.values[2]);
    circle.radius = res.coeffs.values[3];
    circle.normal =
        Eigen::Vector3f(res.coeffs.values[4], res.coeffs.values[5], res.coeffs.values[6]);
    const float norm = circle.normal.norm();
    if (norm < 1e-9f || circle.radius <= 0.0f) {
        ctx.log("degenerate circle fit");
        return false;
    }
    circle.normal /= norm;

    ctx.log("circle: center=(" + std::to_string(circle.center.x()) + ", " +
            std::to_string(circle.center.y()) + ", " + std::to_string(circle.center.z()) +
            "), radius " + std::to_string(circle.radius) + " m, inliers " +
            std::to_string(res.inliers->size()));

    ctx.setOutput("circle", makePortValue(DataType::Circle, circle));
    ctx.setOutput("inliers", makePortValue(DataType::PointCloud, res.inliers));
    return true;
}

} // namespace rvc
