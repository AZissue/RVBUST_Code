#pragma once

#include "pcsearch/core_data/point_cloud.h"
#include "pcsearch/core_data/region.h"

#include <vector>

namespace pcsearch::segmentation {

struct PlaneParams {
    // Max distance from a point to the plane to be counted as inlier (mm).
    double distance_threshold_mm = 1.0;
    int min_inliers = 100;
    int max_planes = 10;
    int ransac_iterations = 1000;
};

// Iterative RANSAC multi-plane detection.
// Returns one Region per detected plane; region.params = [a,b,c,d]
// with a*x+b*y+c*z+d=0 and unit normal (a,b,c). Coordinates in mm.
std::vector<core::Region> detectPlanes(const core::PointCloudData& cloud,
                                       const PlaneParams& params);

}  // namespace pcsearch::segmentation

