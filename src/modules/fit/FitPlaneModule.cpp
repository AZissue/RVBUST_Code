#include "FitPlaneModule.h"

#include "FitUtils.h"
#include "modules/CloudUtils.h"

namespace rvc {

bool FitPlaneModule::execute(ModuleContext& ctx)
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

    RansacResult res = ransacFit(fitted, pcl::SACMODEL_PLANE,
                                 getDouble("distanceThreshold"), getInt("maxIterations"));
    if (!res.ok) {
        ctx.log(res.error);
        return false;
    }

    // 系数 → Plane3D：法线单位化，并统一朝向 +Z 半空间（保证表示唯一）
    Plane3D plane{res.coeffs.values[0], res.coeffs.values[1],
                  res.coeffs.values[2], res.coeffs.values[3]};
    const float norm = std::sqrt(plane.a * plane.a + plane.b * plane.b + plane.c * plane.c);
    if (norm < 1e-9f) {
        ctx.log("degenerate plane normal");
        return false;
    }
    plane.a /= norm;
    plane.b /= norm;
    plane.c /= norm;
    plane.d /= norm;
    plane.alignWith(Eigen::Vector3f(0, 0, 1));

    ctx.log("plane: n=(" + std::to_string(plane.a) + ", " + std::to_string(plane.b) + ", " +
            std::to_string(plane.c) + "), d=" + std::to_string(plane.d) + " m, inliers " +
            std::to_string(res.inliers->size()));

    ctx.setOutput("plane", makePortValue(DataType::Plane, plane));
    ctx.setOutput("inliers", makePortValue(DataType::PointCloud, res.inliers));
    return true;
}

} // namespace rvc
