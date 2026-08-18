#include "FitLineModule.h"

#include "FitUtils.h"
#include "modules/CloudUtils.h"

namespace rvc {

bool FitLineModule::execute(ModuleContext& ctx)
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

    RansacResult res = ransacFit(fitted, pcl::SACMODEL_LINE,
                                 getDouble("distanceThreshold"), getInt("maxIterations"));
    if (!res.ok) {
        ctx.log(res.error);
        return false;
    }

    // 系数 [x,y,z, dx,dy,dz]：线上一点 + 方向
    Line3D line;
    line.point = Eigen::Vector3f(res.coeffs.values[0], res.coeffs.values[1], res.coeffs.values[2]);
    line.direction =
        Eigen::Vector3f(res.coeffs.values[3], res.coeffs.values[4], res.coeffs.values[5]);
    const float norm = line.direction.norm();
    if (norm < 1e-9f) {
        ctx.log("degenerate line direction");
        return false;
    }
    line.direction /= norm;

    ctx.log("line: p=(" + std::to_string(line.point.x()) + ", " + std::to_string(line.point.y()) +
            ", " + std::to_string(line.point.z()) + "), dir=(" +
            std::to_string(line.direction.x()) + ", " + std::to_string(line.direction.y()) +
            ", " + std::to_string(line.direction.z()) + "), inliers " +
            std::to_string(res.inliers->size()));

    ctx.setOutput("line", makePortValue(DataType::Line, line));
    ctx.setOutput("inliers", makePortValue(DataType::PointCloud, res.inliers));
    return true;
}

} // namespace rvc
