#include "BoundingBoxMeasureModule.h"

#include <pcl/common/common.h>

#include "modules/CloudUtils.h"

namespace rvc {

bool BoundingBoxMeasureModule::execute(ModuleContext& ctx)
{
    const PointCloud* cloudIn = ctx.input("cloud").get<PointCloud>();
    if (!cloudIn || !*cloudIn || (*cloudIn)->empty()) {
        ctx.log("no point cloud on input port 'cloud'");
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

    pcl::PointXYZ minPt, maxPt;
    pcl::getMinMax3D(*dense, minPt, maxPt);

    const double sx = maxPt.x - minPt.x;
    const double sy = maxPt.y - minPt.y;
    const double sz = maxPt.z - minPt.z;

    ctx.log("bounding box: " + std::to_string(sx) + " x " + std::to_string(sy) + " x " +
            std::to_string(sz) + " m");

    ctx.setOutput("sizeX", makePortValue(DataType::Scalar, sx));
    ctx.setOutput("sizeY", makePortValue(DataType::Scalar, sy));
    ctx.setOutput("sizeZ", makePortValue(DataType::Scalar, sz));
    return true;
}

} // namespace rvc
