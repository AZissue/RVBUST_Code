#include "pcsearch/segmentation/plane_detector.h"

#include <pcl/ModelCoefficients.h>
#include <pcl/PointIndices.h>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <pcl/sample_consensus/method_types.h>
#include <pcl/sample_consensus/model_types.h>
#include <pcl/segmentation/sac_segmentation.h>

#include <cmath>

namespace pcsearch::segmentation {

namespace {

pcl::PointCloud<pcl::PointXYZ>::Ptr toPclCloud(const core::PointCloudData& cloud) {
    auto out = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    out->resize(cloud.size());
    for (std::int64_t i = 0; i < cloud.size(); ++i) {
        (*out)[i].x = cloud.points(i, 0);
        (*out)[i].y = cloud.points(i, 1);
        (*out)[i].z = cloud.points(i, 2);
    }
    return out;
}

}  // namespace

std::vector<core::Region> detectPlanes(const core::PointCloudData& cloud,
                                       const PlaneParams& params) {
    std::vector<core::Region> result;
    if (cloud.size() == 0) {
        return result;
    }

    pcl::PointCloud<pcl::PointXYZ>::Ptr remaining = toPclCloud(cloud);
    const std::int64_t total = cloud.size();

    for (int plane = 0; plane < params.max_planes; ++plane) {
        pcl::SACSegmentation<pcl::PointXYZ> seg;
        seg.setOptimizeCoefficients(true);
        seg.setModelType(pcl::SACMODEL_PLANE);
        seg.setMethodType(pcl::SAC_RANSAC);
        seg.setDistanceThreshold(params.distance_threshold_mm);
        seg.setMaxIterations(params.ransac_iterations);

        pcl::ModelCoefficients::Ptr coefficients(new pcl::ModelCoefficients);
        pcl::PointIndices::Ptr inliers(new pcl::PointIndices);
        seg.setInputCloud(remaining);
        seg.segment(*inliers, *coefficients);

        if (inliers->indices.size() < static_cast<std::size_t>(params.min_inliers)) {
            break;
        }
        if (coefficients->values.size() < 4) {
            break;
        }

        core::Region region;
        region.id = "plane_" + std::to_string(plane);
        region.label = region.id;
        region.kind = core::Region::Kind::Plane;
        region.indices.reserve(inliers->indices.size());
        for (const auto& idx : inliers->indices) {
            region.indices.push_back(static_cast<std::int64_t>(idx));
        }

        double a = coefficients->values[0];
        double b = coefficients->values[1];
        double c = coefficients->values[2];
        double d = coefficients->values[3];
        const double norm = std::sqrt(a * a + b * b + c * c);
        if (norm > 1e-12) {
            a /= norm;
            b /= norm;
            c /= norm;
            d /= norm;
        }
        region.params = {a, b, c, d};
        result.push_back(std::move(region));

        // Remove inliers and continue with the rest.
        pcl::PointCloud<pcl::PointXYZ>::Ptr next(new pcl::PointCloud<pcl::PointXYZ>);
        next->reserve(remaining->size() - inliers->indices.size());
        std::vector<char> keep(remaining->size(), 1);
        for (const auto& idx : inliers->indices) {
            keep[static_cast<std::size_t>(idx)] = 0;
        }
        for (std::size_t i = 0; i < remaining->size(); ++i) {
            if (keep[i]) {
                next->push_back((*remaining)[i]);
            }
        }
        remaining = next;
        if (remaining->size() < static_cast<std::size_t>(params.min_inliers)) {
            break;
        }
    }

    return result;
}

}  // namespace pcsearch::segmentation

