#include "BoxRoiModule.h"

#include <pcl/filters/crop_box.h>

#include "modules/CloudUtils.h"

namespace rvc {

bool BoxRoiModule::execute(ModuleContext& ctx)
{
    const PointCloud* cloudIn = ctx.input("cloud").get<PointCloud>();
    if (!cloudIn || !*cloudIn || (*cloudIn)->empty()) {
        ctx.log("no point cloud on input port 'cloud'");
        return false;
    }

    const float xmin = static_cast<float>(getDouble("xmin"));
    const float xmax = static_cast<float>(getDouble("xmax"));
    const float ymin = static_cast<float>(getDouble("ymin"));
    const float ymax = static_cast<float>(getDouble("ymax"));
    const float zmin = static_cast<float>(getDouble("zmin"));
    const float zmax = static_cast<float>(getDouble("zmax"));
    if (xmin > xmax || ymin > ymax || zmin > zmax) {
        ctx.log("invalid ROI: min > max on some axis");
        return false;
    }

    const PointCloud dense = removeNaNIfNeeded(*cloudIn);

    pcl::CropBox<pcl::PointXYZ> crop;
    crop.setInputCloud(dense);
    crop.setMin(Eigen::Vector4f(xmin, ymin, zmin, 1.0f));
    crop.setMax(Eigen::Vector4f(xmax, ymax, zmax, 1.0f));
    auto out = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    crop.filter(*out);

    ctx.log("ROI [" + std::to_string(xmin) + ".." + std::to_string(xmax) + "]x[" +
            std::to_string(ymin) + ".." + std::to_string(ymax) + "]x[" +
            std::to_string(zmin) + ".." + std::to_string(zmax) + "]: " +
            std::to_string((*cloudIn)->size()) + " -> " + std::to_string(out->size()) + " points");
    if (out->empty()) {
        ctx.log("ROI result is empty");
        return false;
    }

    ctx.setOutput("cloud", makePortValue(DataType::PointCloud, PointCloud(out)));

    // 导出当前 ROI 供下游模块订阅（拟合/测量模块的 roi 输入端口）
    const RoiBox roi = RoiBox::fromMinMax({xmin, ymin, zmin}, {xmax, ymax, zmax});
    ctx.setOutput("roi", makePortValue(DataType::Roi, roi));
    return true;
}

} // namespace rvc
