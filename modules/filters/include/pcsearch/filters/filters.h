#pragma once

#include "pcsearch/core_data/point_cloud.h"

#include <Eigen/Core>

#include <cstdint>
#include <vector>

namespace pcsearch::filters {

// Result of a filtering operation: the new cloud plus the mapping from each
// output row back to its input row index (needed to keep provenance).
struct FilterResult {
    core::PointCloudData cloud;
    std::vector<std::int64_t> source_indices;
};

enum class Axis { X, Y, Z };

enum class VoxelMode { Centroid, Center };

// Drop rows where any coordinate is NaN/Inf.
FilterResult removeInvalidPoints(const core::PointCloudData& cloud);

// Voxel grid downsampling (uniform grid, internal unit mm).
// Centroid: output the mean position (and mean color) of each occupied voxel.
// Center:   output the voxel center.
FilterResult voxelDownsample(const core::PointCloudData& cloud, double leaf_size_mm,
                             VoxelMode mode = VoxelMode::Centroid);

// Uniform random sampling without replacement down to target_count points.
FilterResult randomDownsample(const core::PointCloudData& cloud,
                              std::int64_t target_count, unsigned seed = 0);

// Keep points whose coordinate on `axis` is within [min_mm, max_mm].
FilterResult filterByAxisRange(const core::PointCloudData& cloud, Axis axis,
                               double min_mm, double max_mm);

// Axis-aligned bounding box over valid (finite) points only, in mm.
// Rows containing NaN/Inf are skipped, matching the semantics of PCL
// getMinMax3D / Open3D get_axis_aligned_bounding_box. Returns false when the
// cloud is empty or has no finite point (min/max left untouched).
bool computeBounds(const core::PointCloudData& cloud, Eigen::Vector3f& min,
                   Eigen::Vector3f& max, std::int64_t* valid_points = nullptr);

}  // namespace pcsearch::filters
