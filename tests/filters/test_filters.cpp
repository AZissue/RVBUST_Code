#include "pcsearch/filters/filters.h"

#include <cmath>
#include <cstdint>
#include <iostream>
#include <limits>
#include <set>

namespace {

using pcsearch::core::PointCloudData;
using pcsearch::filters::Axis;
using pcsearch::filters::computeBounds;
using pcsearch::filters::filterByAxisRange;
using pcsearch::filters::randomDownsample;
using pcsearch::filters::removeInvalidPoints;
using pcsearch::filters::voxelDownsample;

int check(bool ok, const char* msg) {
    if (!ok) {
        std::cerr << "FAIL: " << msg << "\n";
        return 1;
    }
    return 0;
}

PointCloudData makeCloudWithInvalid() {
    PointCloudData c;
    c.points.resize(1000, 3);
    c.colors.resize(1000, 3);
    c.normals.resize(1000, 3);
    c.scalar_channels = {{}};
    c.scalar_channel_names = {"confidence"};
    std::int64_t r = 0;
    for (int i = 0; i < 10; ++i) {
        for (int j = 0; j < 99; ++j) {
            c.points(r, 0) = static_cast<float>(i);
            c.points(r, 1) = static_cast<float>(j);
            c.points(r, 2) = 0.0f;
            c.colors.row(r).setConstant(0.5f);
            c.normals.row(r) << 0.0f, 0.0f, 1.0f;
            c.scalar_channels[0].push_back(static_cast<float>(r));
            ++r;
        }
        // one invalid point per row
        c.points(r, 0) = std::nanf("");
        c.points(r, 1) = 0.0f;
        c.points(r, 2) = 0.0f;
        c.colors.row(r).setConstant(0.0f);
        c.normals.row(r) << 0.0f, 0.0f, 0.0f;
        c.scalar_channels[0].push_back(-1.0f);
        ++r;
    }
    return c;
}

}  // namespace

int main() {
    int failures = 0;

    // 1) removeInvalidPoints
    {
        const auto src = makeCloudWithInvalid();
        const auto r = removeInvalidPoints(src);
        failures += check(r.cloud.size() == 990, "removeInvalid: count");
        failures += check(static_cast<std::int64_t>(r.source_indices.size()) == r.cloud.size(),
                          "removeInvalid: map size");
        failures += check(r.cloud.hasNormals(), "removeInvalid: normals preserved");
        failures += check(r.cloud.scalar_channels.size() == 1, "removeInvalid: scalar channels preserved");
        for (std::int64_t i = 0; i < r.cloud.size(); ++i) {
            if (!r.cloud.points.row(i).allFinite()) {
                failures += check(false, "removeInvalid: NaN remains");
                break;
            }
        }
        // Invalid rows (NaN points) had scalar=-1; after removal no -1 should remain.
        if (!r.cloud.scalar_channels.empty()) {
            for (float v : r.cloud.scalar_channels[0]) {
                if (v < 0.0f) {
                    failures += check(false, "removeInvalid: invalid scalar leaked");
                    break;
                }
            }
        }
    }

    // 2) voxelDownsample on a 100x100 grid with 1mm spacing, leaf 10mm
    {
        PointCloudData c;
        c.points.resize(10000, 3);
        c.normals.resize(10000, 3);
        c.scalar_channels = {{}};
        c.scalar_channel_names = {"intensity"};
        std::int64_t r = 0;
        for (int i = 0; i < 100; ++i) {
            for (int j = 0; j < 100; ++j) {
                c.points(r, 0) = static_cast<float>(i);
                c.points(r, 1) = static_cast<float>(j);
                c.points(r, 2) = 0.0f;
                c.normals.row(r) << 0.0f, 0.0f, 1.0f;
                c.scalar_channels[0].push_back(static_cast<float>(r));
                ++r;
            }
        }
        const auto vox = voxelDownsample(c, 10.0);
        failures += check(vox.cloud.size() == 100, "voxel: expected 100 voxels");
        failures += check(vox.cloud.hasNormals(), "voxel: normals preserved");
        failures += check(vox.cloud.scalar_channels.size() == 1, "voxel: scalar channels preserved");
        if (vox.cloud.size() == 100) {
            for (std::int64_t i = 0; i < vox.cloud.size(); ++i) {
                const float x = vox.cloud.points(i, 0);
                const float y = vox.cloud.points(i, 1);
                // Grid 0..99 mm, leaf 10 mm -> centroids at k*10+4.5.
                const float expected_x = std::floor(x / 10.0f) * 10.0f + 4.5f;
                const float expected_y = std::floor(y / 10.0f) * 10.0f + 4.5f;
                failures += check(std::abs(x - expected_x) < 1e-3f &&
                                      std::abs(y - expected_y) < 1e-3f,
                                  "voxel: centroid position");
                failures += check(std::abs(vox.cloud.normals(i, 2) - 1.0f) < 1e-4f,
                                  "voxel: normal averaged to (0,0,1)");
            }
        }
    }

    // 3) randomDownsample
    {
        PointCloudData c;
        c.points.resize(500, 3);
        c.normals.resize(500, 3);
        c.scalar_channels = {{}};
        c.scalar_channel_names = {"intensity"};
        for (std::int64_t i = 0; i < 500; ++i) {
            c.points(i, 0) = static_cast<float>(i);
            c.points(i, 1) = 0.0f;
            c.points(i, 2) = 0.0f;
            c.normals.row(i) << 0.0f, 0.0f, 1.0f;
            c.scalar_channels[0].push_back(static_cast<float>(i));
        }
        const auto r = randomDownsample(c, 50, 42);
        failures += check(r.cloud.size() == 50, "random: count");
        failures += check(r.cloud.hasNormals(), "random: normals preserved");
        failures += check(r.cloud.scalar_channels.size() == 1, "random: scalar channels preserved");
        std::set<std::int64_t> seen;
        for (const auto& s : r.source_indices) {
            failures += check(s >= 0 && s < 500, "random: index in range");
            seen.insert(s);
        }
        failures += check(seen.size() == 50, "random: unique");
        // Scalar values should match the source indices.
        if (r.cloud.scalar_channels.size() == 1) {
            for (std::int64_t k = 0; k < r.cloud.size(); ++k) {
                const std::int64_t src = r.source_indices[static_cast<std::size_t>(k)];
                failures += check(r.cloud.scalar_channels[0][static_cast<std::size_t>(k)] ==
                                      static_cast<float>(src),
                                  "random: scalar copied from source");
            }
        }
    }

    // 4) filterByAxisRange
    {
        PointCloudData c;
        c.points.resize(101, 3);
        c.normals.resize(101, 3);
        c.scalar_channels = {{}};
        c.scalar_channel_names = {"intensity"};
        for (std::int64_t i = 0; i < 101; ++i) {
            c.points(i, 0) = static_cast<float>(i - 50);  // -50 .. 50
            c.points(i, 1) = 0.0f;
            c.points(i, 2) = 0.0f;
            c.normals.row(i) << 0.0f, 0.0f, 1.0f;
            c.scalar_channels[0].push_back(static_cast<float>(i));
        }
        const auto r = filterByAxisRange(c, Axis::X, -10.0, 10.0);
        failures += check(r.cloud.size() == 21, "zfilter: count");
        failures += check(r.cloud.hasNormals(), "zfilter: normals preserved");
        failures += check(r.cloud.scalar_channels.size() == 1, "zfilter: scalar channels preserved");
        if (r.cloud.scalar_channels.size() == 1) {
            for (std::int64_t k = 0; k < r.cloud.size(); ++k) {
                const std::int64_t src = r.source_indices[static_cast<std::size_t>(k)];
                failures += check(r.cloud.scalar_channels[0][static_cast<std::size_t>(k)] ==
                                      static_cast<float>(src),
                                  "zfilter: scalar copied from source");
            }
        }
    }

    // 5) computeBounds must ignore NaN/Inf (RVC depth maps contain holes)
    {
        PointCloudData c;
        c.points.resize(200, 3);
        std::int64_t r = 0;
        // First point is NaN - the classic case that used to poison min/max.
        c.points(r, 0) = std::nanf("");
        c.points(r, 1) = std::nanf("");
        c.points(r, 2) = std::nanf("");
        ++r;
        // One +Inf and one -Inf point.
        c.points(r, 0) = std::numeric_limits<float>::infinity();
        c.points(r, 1) = 0.0f;
        c.points(r, 2) = 0.0f;
        ++r;
        c.points(r, 0) = -std::numeric_limits<float>::infinity();
        c.points(r, 1) = 0.0f;
        c.points(r, 2) = 0.0f;
        ++r;
        // Finite grid -10..-1 x 10..20.
        for (int i = -10; i < 0; ++i) {
            for (int j = 10; j <= 20; ++j) {
                c.points(r, 0) = static_cast<float>(i);
                c.points(r, 1) = static_cast<float>(j);
                c.points(r, 2) = 5.0f;
                ++r;
            }
        }
        c.points.conservativeResize(r, 3);

        Eigen::Vector3f mn, mx;
        std::int64_t valid = -1;
        const bool ok = computeBounds(c, mn, mx, &valid);
        failures += check(ok, "bounds: has valid points");
        failures += check(valid == 110, "bounds: valid count (2 inf + 110 grid)");
        failures += check(ok && mn.x() == -10.0f && mx.x() == -1.0f &&
                              mn.y() == 10.0f && mx.y() == 20.0f &&
                              mn.z() == 5.0f && mx.z() == 5.0f,
                          "bounds: finite min/max only");

        // All-invalid cloud must fail (no garbage bounds).
        PointCloudData bad;
        bad.points.resize(5, 3);
        bad.points.setConstant(std::nanf(""));
        failures += check(!computeBounds(bad, mn, mx), "bounds: all NaN fails");
    }

    if (failures == 0) {
        std::cout << "PASS\n";
        return 0;
    }
    std::cerr << failures << " checks failed\n";
    return 1;
}
