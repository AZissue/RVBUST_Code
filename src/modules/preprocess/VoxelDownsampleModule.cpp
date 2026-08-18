#include "VoxelDownsampleModule.h"

#include <pcl/filters/voxel_grid.h>

#include "modules/CloudUtils.h"

namespace rvc {

bool VoxelDownsampleModule::execute(ModuleContext& ctx)
{
    const PointCloud* cloudIn = ctx.input("cloud").get<PointCloud>();
    if (!cloudIn || !*cloudIn || (*cloudIn)->empty()) {
        ctx.log("no point cloud on input port 'cloud'");
        return false;
    }

    const double leaf = getDouble("leafSize");
    if (leaf <= 0.0) {
        ctx.log("leafSize must be positive");
        return false;
    }

    pcl::VoxelGrid<pcl::PointXYZ> voxel;
    voxel.setInputCloud(removeNaNIfNeeded(*cloudIn));
    voxel.setLeafSize(static_cast<float>(leaf), static_cast<float>(leaf), static_cast<float>(leaf));
    auto out = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    voxel.filter(*out);

    ctx.log("downsampled " + std::to_string((*cloudIn)->size()) + " -> " +
            std::to_string(out->size()) + " points (leaf " + std::to_string(leaf) + " m)");
    if (out->empty()) {
        ctx.log("downsample result is empty");
        return false;
    }

    ctx.setOutput("cloud", makePortValue(DataType::PointCloud, PointCloud(out)));
    return true;
}

} // namespace rvc
