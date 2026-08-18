#pragma once

// 拟合模块共享的 RANSAC 封装（PCL SACSegmentation）。

#include <pcl/ModelCoefficients.h>
#include <pcl/PointIndices.h>
#include <pcl/filters/extract_indices.h>
#include <pcl/sample_consensus/method_types.h>
#include <pcl/sample_consensus/model_types.h>
#include <pcl/segmentation/sac_segmentation.h>

#include "modules/CloudUtils.h"

namespace rvc {

struct RansacResult {
    bool ok = false;
    pcl::ModelCoefficients coeffs;
    PointCloud inliers = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    std::string error;
};

// 通用 RANSAC 拟合：输入点云先去 NaN；内点 <50 或 <输入 3% 视为拟合失败。
inline RansacResult ransacFit(const PointCloud& cloudIn, int modelType,
                              double distanceThreshold, int maxIterations,
                              double radiusMin = 0.0, double radiusMax = 0.0)
{
    RansacResult res;
    if (!cloudIn || cloudIn->empty()) {
        res.error = "input point cloud is empty";
        return res;
    }

    const PointCloud dense = removeNaNIfNeeded(cloudIn);
    if (dense->size() < 10) {
        res.error = "too few valid points after NaN removal: " + std::to_string(dense->size());
        return res;
    }

    pcl::SACSegmentation<pcl::PointXYZ> seg;
    seg.setOptimizeCoefficients(true);
    seg.setModelType(modelType);
    seg.setMethodType(pcl::SAC_RANSAC);
    seg.setDistanceThreshold(distanceThreshold);
    seg.setMaxIterations(maxIterations);
    if (radiusMax > radiusMin && radiusMin > 0.0)
        seg.setRadiusLimits(radiusMin, radiusMax);
    seg.setInputCloud(dense);

    pcl::PointIndices::Ptr indices(new pcl::PointIndices);
    seg.segment(*indices, res.coeffs);

    const size_t minInliers = std::max<size_t>(50, dense->size() * 3 / 100);
    if (indices->indices.size() < minInliers || res.coeffs.values.empty()) {
        res.error = "fit failed: inliers " + std::to_string(indices->indices.size()) +
                    " < required " + std::to_string(minInliers) + " (of " +
                    std::to_string(dense->size()) + " points)";
        return res;
    }

    pcl::ExtractIndices<pcl::PointXYZ> extract;
    extract.setInputCloud(dense);
    extract.setIndices(indices);
    extract.setNegative(false);
    extract.filter(*res.inliers);

    res.ok = true;
    return res;
}

} // namespace rvc
