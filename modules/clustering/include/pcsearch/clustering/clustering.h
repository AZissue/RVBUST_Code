#pragma once

#include "pcsearch/core_data/point_cloud.h"
#include "pcsearch/core_data/region.h"

#include <cstdint>
#include <vector>

namespace pcsearch::clustering {

struct DbscanParams {
    double eps_mm = 5.0;
    int min_points = 10;
};

struct EuclideanParams {
    double tolerance_mm = 5.0;
    int min_cluster_size = 50;
    int max_cluster_size = 100000;
};

// DBSCAN density clustering. Points that cannot reach any core point are
// returned via `noise` (may be null). Regions use indices into the input cloud.
std::vector<core::Region> dbscan(const core::PointCloudData& cloud,
                                 const DbscanParams& params,
                                 std::vector<std::int64_t>* noise = nullptr);

// Euclidean (region-growing) cluster extraction, PCL-style.
std::vector<core::Region> euclideanClusters(const core::PointCloudData& cloud,
                                            const EuclideanParams& params);

}  // namespace pcsearch::clustering

