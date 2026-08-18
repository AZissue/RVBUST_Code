#pragma once

// 点云模块共享小工具（header-only）。

#include <pcl/filters/filter.h>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>

#include "core/ModuleBase.h"

namespace rvc {

// is_dense=false 的点云先移除 NaN（RVC PointMap 转换来的点云含无效点）。
// 返回处理后的点云；若已是 dense 则原样返回。
inline PointCloud removeNaNIfNeeded(const PointCloud& cloud)
{
    if (!cloud || cloud->is_dense)
        return cloud;
    auto out = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    std::vector<int> indices;
    pcl::removeNaNFromPointCloud(*cloud, *out, indices);
    out->is_dense = true;
    return out;
}

// 按 RoiBox 过滤点云（含边界）；roi.valid=false 时原样返回。
inline PointCloud cropByRoi(const PointCloud& cloud, const RoiBox& roi)
{
    if (!cloud || !roi.valid)
        return cloud;
    auto out = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    out->reserve(cloud->size());
    for (const auto& p : cloud->points) {
        if (roi.contains(p.x, p.y, p.z))
            out->push_back(p);
    }
    out->width = static_cast<std::uint32_t>(out->size());
    out->height = 1;
    out->is_dense = true;
    return out;
}

// ---- ROI 参数组（拟合/测量模块自有 ROI，配合可选 roi 输入端口使用）----

// 在模块构造时声明自有 ROI 参数组
inline void declareRoiParams(ModuleBase& module, const char* prefix = "roi")
{
    const std::string p = prefix;
    module.declareParam({p + "Enabled", ParamType::Bool, false});
    module.declareParam({p + "Is2D", ParamType::Bool, false});
    module.declareParam({p + "Xmin", ParamType::Double, -1e9});
    module.declareParam({p + "Xmax", ParamType::Double, 1e9});
    module.declareParam({p + "Ymin", ParamType::Double, -1e9});
    module.declareParam({p + "Ymax", ParamType::Double, 1e9});
    module.declareParam({p + "Zmin", ParamType::Double, -1e9});
    module.declareParam({p + "Zmax", ParamType::Double, 1e9});
}

// 解析模块生效 ROI：连线 roi 端口 > 自有参数（roiEnabled=true）> 不裁（valid=false）
inline RoiBox resolveRoi(const ModuleContext& ctx, const ModuleBase& module,
                         const char* prefix = "roi")
{
    if (const RoiBox* linked = ctx.input("roi").get<RoiBox>())
        return *linked;

    const std::string p = prefix;
    if (!module.getBool(p + "Enabled"))
        return {};
    return RoiBox::fromMinMax(
        {static_cast<float>(module.getDouble(p + "Xmin")),
         static_cast<float>(module.getDouble(p + "Ymin")),
         static_cast<float>(module.getDouble(p + "Zmin"))},
        {static_cast<float>(module.getDouble(p + "Xmax")),
         static_cast<float>(module.getDouble(p + "Ymax")),
         static_cast<float>(module.getDouble(p + "Zmax"))},
        module.getBool(p + "Is2D"));
}

// 从模块参数组读取完整 ROI（含 2D 标志），供 ROI 编辑弹窗初始化。
inline RoiBox readRoiFromParams(const ModuleBase& module, const char* prefix = "roi")
{
    const std::string p = prefix;
    if (!module.getBool(p + "Enabled"))
        return {};
    return RoiBox::fromMinMax(
        {static_cast<float>(module.getDouble(p + "Xmin")),
         static_cast<float>(module.getDouble(p + "Ymin")),
         static_cast<float>(module.getDouble(p + "Zmin"))},
        {static_cast<float>(module.getDouble(p + "Xmax")),
         static_cast<float>(module.getDouble(p + "Ymax")),
         static_cast<float>(module.getDouble(p + "Zmax"))},
        module.getBool(p + "Is2D"));
}

// 3D 视口框选回写 / ROI 弹窗确认：把 RoiBox 写入模块的自有 ROI 参数组并启用。
// 目标模块没有 ROI 参数组时返回 false。
inline bool writeRoiToParams(ModuleBase& module, const RoiBox& roi, const char* prefix = "roi")
{
    const std::string p = prefix;
    bool ok = true;
    ok &= module.setParam(p + "Xmin", static_cast<double>(roi.min.x()));
    ok &= module.setParam(p + "Ymin", static_cast<double>(roi.min.y()));
    ok &= module.setParam(p + "Zmin", static_cast<double>(roi.min.z()));
    ok &= module.setParam(p + "Xmax", static_cast<double>(roi.max.x()));
    ok &= module.setParam(p + "Ymax", static_cast<double>(roi.max.y()));
    ok &= module.setParam(p + "Zmax", static_cast<double>(roi.max.z()));
    ok &= module.setParam(p + "Enabled", true);
    ok &= module.setParam(p + "Is2D", roi.is2D);
    return ok;
}

} // namespace rvc
