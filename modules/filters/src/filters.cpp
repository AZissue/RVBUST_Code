#include "pcsearch/filters/filters.h"

#include <Eigen/Core>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <random>
#include <unordered_map>
#include <vector>

namespace pcsearch::filters {

namespace {

using core::PointCloudData;

void copyRow(const PointCloudData& src, std::int64_t from, PointCloudData& dst,
             std::int64_t to) {
    dst.points.row(to) = src.points.row(from);
    if (src.hasColors() && dst.hasColors()) {
        dst.colors.row(to) = src.colors.row(from);
    }
    if (src.hasNormals() && dst.hasNormals()) {
        dst.normals.row(to) = src.normals.row(from);
    }
}

}  // namespace

FilterResult removeInvalidPoints(const PointCloudData& cloud) {
    FilterResult result;
    result.cloud.unit = cloud.unit;
    result.cloud.source_path = cloud.source_path;
    result.cloud.frame_id = cloud.frame_id;

    std::vector<std::int64_t> keep;
    keep.reserve(static_cast<std::size_t>(cloud.size()));
    for (std::int64_t i = 0; i < cloud.size(); ++i) {
        const Eigen::Vector3f p = cloud.points.row(i);
        if (p.allFinite()) {
            keep.push_back(i);
        }
    }
    result.cloud.points.resize(static_cast<std::int64_t>(keep.size()), 3);
    if (cloud.hasColors()) result.cloud.colors.resize(result.cloud.size(), 3);
    if (cloud.hasNormals()) result.cloud.normals.resize(result.cloud.size(), 3);
    result.cloud.scalar_channels.resize(cloud.scalar_channels.size());
    result.cloud.scalar_channel_names = cloud.scalar_channel_names;
    for (std::size_t c = 0; c < cloud.scalar_channels.size(); ++c) {
        result.cloud.scalar_channels[c].reserve(keep.size());
    }
    for (std::size_t k = 0; k < keep.size(); ++k) {
        copyRow(cloud, keep[k], result.cloud, static_cast<std::int64_t>(k));
        for (std::size_t c = 0; c < cloud.scalar_channels.size(); ++c) {
            result.cloud.scalar_channels[c].push_back(
                cloud.scalar_channels[c][static_cast<std::size_t>(keep[k])]);
        }
    }
    result.source_indices = keep;
    return result;
}

namespace {

struct VoxelKey {
    int x = 0;
    int y = 0;
    int z = 0;
    bool operator==(const VoxelKey& other) const noexcept = default;
};

struct VoxelKeyHash {
    std::size_t operator()(const VoxelKey& k) const noexcept {
        // boost::hash_combine style: keep the three grid coordinates
        // distinguishable and avoid the collisions of the old scalar XOR hash.
        std::size_t h = static_cast<std::uint32_t>(k.x);
        h ^= (static_cast<std::uint32_t>(k.y) + 0x9e3779b97f4a7c15ULL +
              (h << 6) + (h >> 2));
        h ^= (static_cast<std::uint32_t>(k.z) + 0x9e3779b97f4a7c15ULL +
              (h << 6) + (h >> 2));
        return h;
    }
};

struct VoxelAccum {
    Eigen::Vector3d sum = Eigen::Vector3d::Zero();
    Eigen::Vector3d color_sum = Eigen::Vector3d::Zero();
    Eigen::Vector3d normal_sum = Eigen::Vector3d::Zero();
    std::vector<double> scalar_sums;
    std::int64_t count = 0;
    std::int64_t first_index = -1;
    Eigen::Vector3i grid_index = Eigen::Vector3i::Zero();
};

}  // namespace

FilterResult voxelDownsample(const PointCloudData& cloud, double leaf_size_mm,
                             VoxelMode mode) {
    FilterResult result;
    result.cloud.unit = cloud.unit;
    result.cloud.source_path = cloud.source_path;
    result.cloud.frame_id = cloud.frame_id;
    if (cloud.size() == 0 || leaf_size_mm <= 0.0) {
        result.cloud = cloud;
        result.source_indices.resize(cloud.size());
        for (std::int64_t i = 0; i < cloud.size(); ++i) result.source_indices[i] = i;
        return result;
    }

    // Use the same finite-only bounds routine as the rest of the pipeline so
    // that NaN/Inf holes in RVC depth maps do not poison the voxel grid origin.
    Eigen::Vector3f min_f;
    Eigen::Vector3f max_f;
    if (!computeBounds(cloud, min_f, max_f)) {
        // No finite point: return an empty cloud with the same metadata.
        result.cloud.scalar_channel_names = cloud.scalar_channel_names;
        return result;
    }

    const Eigen::Vector3d min_b = min_f.cast<double>();
    std::unordered_map<VoxelKey, VoxelAccum, VoxelKeyHash> voxels;
    voxels.reserve(static_cast<std::size_t>(cloud.size() / 2 + 1));

    const std::size_t scalar_count = cloud.scalar_channels.size();
    for (std::int64_t i = 0; i < cloud.size(); ++i) {
        const Eigen::Vector3d p = cloud.points.row(i).cast<double>();
        if (!p.allFinite()) continue;
        const Eigen::Vector3d idx_d = (p - min_b).array() / leaf_size_mm;
        const Eigen::Vector3i idx = idx_d.cast<int>();
        const VoxelKey key{idx.x(), idx.y(), idx.z()};
        VoxelAccum& v = voxels[key];
        if (v.count == 0) {
            v.scalar_sums.assign(scalar_count, 0.0);
        }
        v.grid_index = idx;
        v.sum += p;
        if (cloud.hasColors()) v.color_sum += cloud.colors.row(i).cast<double>();
        if (cloud.hasNormals()) v.normal_sum += cloud.normals.row(i).cast<double>();
        for (std::size_t c = 0; c < scalar_count; ++c) {
            v.scalar_sums[c] += cloud.scalar_channels[c][static_cast<std::size_t>(i)];
        }
        ++v.count;
        if (v.first_index < 0) v.first_index = i;
    }

    result.cloud.points.resize(static_cast<std::int64_t>(voxels.size()), 3);
    if (cloud.hasColors()) result.cloud.colors.resize(result.cloud.size(), 3);
    if (cloud.hasNormals()) result.cloud.normals.resize(result.cloud.size(), 3);
    result.cloud.scalar_channels.resize(scalar_count);
    result.cloud.scalar_channel_names = cloud.scalar_channel_names;
    for (std::size_t c = 0; c < scalar_count; ++c) {
        result.cloud.scalar_channels[c].resize(voxels.size());
    }
    result.source_indices.reserve(voxels.size());

    // Sort by first encountered source index so output order is deterministic
    // across runs and platforms (unordered_map iteration order is not).
    std::vector<const std::pair<const VoxelKey, VoxelAccum>*> sorted;
    sorted.reserve(voxels.size());
    for (const auto& entry : voxels) {
        sorted.push_back(&entry);
    }
    std::sort(sorted.begin(), sorted.end(),
              [](const auto* a, const auto* b) {
                  return a->second.first_index < b->second.first_index;
              });

    std::int64_t row = 0;
    for (const auto* e : sorted) {
        const VoxelAccum& v = e->second;
        Eigen::Vector3d out;
        if (mode == VoxelMode::Centroid) {
            out = v.sum / static_cast<double>(v.count);
        } else {
            out = min_b + (v.grid_index.cast<double>() + Eigen::Vector3d::Constant(0.5)) *
                              leaf_size_mm;
        }
        result.cloud.points(row, 0) = static_cast<float>(out.x());
        result.cloud.points(row, 1) = static_cast<float>(out.y());
        result.cloud.points(row, 2) = static_cast<float>(out.z());
        if (cloud.hasColors()) {
            result.cloud.colors.row(row) = (v.color_sum / static_cast<double>(v.count)).cast<float>();
        }
        if (cloud.hasNormals()) {
            result.cloud.normals.row(row) = (v.normal_sum / static_cast<double>(v.count)).cast<float>();
        }
        for (std::size_t c = 0; c < scalar_count; ++c) {
            result.cloud.scalar_channels[c][static_cast<std::size_t>(row)] =
                static_cast<float>(v.scalar_sums[c] / static_cast<double>(v.count));
        }
        result.source_indices.push_back(v.first_index);
        ++row;
    }
    return result;
}

FilterResult randomDownsample(const PointCloudData& cloud, std::int64_t target_count,
                              unsigned seed) {
    FilterResult result;
    result.cloud.unit = cloud.unit;
    result.cloud.source_path = cloud.source_path;
    result.cloud.frame_id = cloud.frame_id;
    const std::int64_t n = cloud.size();
    if (target_count >= n) {
        result.cloud = cloud;
        result.source_indices.resize(static_cast<std::size_t>(n));
        for (std::int64_t i = 0; i < n; ++i) result.source_indices[i] = i;
        return result;
    }
    std::vector<std::int64_t> idx(static_cast<std::size_t>(n));
    for (std::int64_t i = 0; i < n; ++i) idx[static_cast<std::size_t>(i)] = i;
    std::mt19937 rng(seed);
    std::shuffle(idx.begin(), idx.end(), rng);
    idx.resize(static_cast<std::size_t>(target_count));
    std::sort(idx.begin(), idx.end());

    result.cloud.points.resize(target_count, 3);
    if (cloud.hasColors()) result.cloud.colors.resize(target_count, 3);
    if (cloud.hasNormals()) result.cloud.normals.resize(target_count, 3);
    result.cloud.scalar_channels.resize(cloud.scalar_channels.size());
    result.cloud.scalar_channel_names = cloud.scalar_channel_names;
    for (std::size_t c = 0; c < cloud.scalar_channels.size(); ++c) {
        result.cloud.scalar_channels[c].resize(static_cast<std::size_t>(target_count));
    }
    for (std::int64_t r = 0; r < target_count; ++r) {
        const std::int64_t src_row = idx[static_cast<std::size_t>(r)];
        copyRow(cloud, src_row, result.cloud, r);
        for (std::size_t c = 0; c < cloud.scalar_channels.size(); ++c) {
            result.cloud.scalar_channels[c][static_cast<std::size_t>(r)] =
                cloud.scalar_channels[c][static_cast<std::size_t>(src_row)];
        }
    }
    result.source_indices = idx;
    return result;
}

FilterResult filterByAxisRange(const PointCloudData& cloud, Axis axis,
                               double min_mm, double max_mm) {
    FilterResult result;
    result.cloud.unit = cloud.unit;
    result.cloud.source_path = cloud.source_path;
    result.cloud.frame_id = cloud.frame_id;
    std::vector<std::int64_t> keep;
    keep.reserve(static_cast<std::size_t>(cloud.size()));
    const int col = axis == Axis::X ? 0 : (axis == Axis::Y ? 1 : 2);
    for (std::int64_t i = 0; i < cloud.size(); ++i) {
        const float v = cloud.points(i, col);
        if (v >= min_mm && v <= max_mm) {
            keep.push_back(i);
        }
    }
    result.cloud.points.resize(static_cast<std::int64_t>(keep.size()), 3);
    if (cloud.hasColors()) result.cloud.colors.resize(result.cloud.size(), 3);
    if (cloud.hasNormals()) result.cloud.normals.resize(result.cloud.size(), 3);
    result.cloud.scalar_channels.resize(cloud.scalar_channels.size());
    result.cloud.scalar_channel_names = cloud.scalar_channel_names;
    for (std::size_t c = 0; c < cloud.scalar_channels.size(); ++c) {
        result.cloud.scalar_channels[c].resize(keep.size());
    }
    for (std::size_t k = 0; k < keep.size(); ++k) {
        const std::int64_t src_row = keep[k];
        copyRow(cloud, src_row, result.cloud, static_cast<std::int64_t>(k));
        for (std::size_t c = 0; c < cloud.scalar_channels.size(); ++c) {
            result.cloud.scalar_channels[c][k] =
                cloud.scalar_channels[c][static_cast<std::size_t>(src_row)];
        }
    }
    result.source_indices = keep;
    return result;
}

bool computeBounds(const core::PointCloudData& cloud, Eigen::Vector3f& min,
                   Eigen::Vector3f& max, std::int64_t* valid_points) {
    bool found = false;
    std::int64_t valid = 0;
    Eigen::Vector3f mn = Eigen::Vector3f::Constant(std::numeric_limits<float>::max());
    Eigen::Vector3f mx = Eigen::Vector3f::Constant(std::numeric_limits<float>::lowest());
    for (std::int64_t i = 0; i < cloud.size(); ++i) {
        const Eigen::Vector3f p = cloud.points.row(i);
        // NaN/Inf must never touch the result: a NaN comparison is always
        // false, which would silently corrupt min/max (and later show up as
        // ±1e9 after range clamping in the parameter UI).
        if (!p.allFinite()) continue;
        mn = mn.cwiseMin(p);
        mx = mx.cwiseMax(p);
        found = true;
        ++valid;
    }
    if (valid_points) *valid_points = valid;
    if (!found) return false;
    min = mn;
    max = mx;
    return true;
}

}  // namespace pcsearch::filters
