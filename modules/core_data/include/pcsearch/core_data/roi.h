#pragma once

#include <Eigen/Core>

#include <algorithm>

namespace pcsearch::core {

// ROI box in internal units (mm). The box is defined by its world-space
// center, half extents along its local axes (min/max are the local-space
// bounds relative to the center) and an orientation matrix that maps local
// coordinates to world coordinates. With orientation == Identity the box is
// axis-aligned and `contains()` behaves exactly like a world-space AABB test.
// Produced by the box_roi node (or by interactive 3D selection) and consumed
// by ROI-aware nodes such as roi_crop. An unset box means "no region".
struct RoiBox {
    // Local-space bounds relative to `center` (mm).
    Eigen::Vector3f min = Eigen::Vector3f::Zero();
    Eigen::Vector3f max = Eigen::Vector3f::Zero();
    // World-space center of the box (mm).
    Eigen::Vector3f center = Eigen::Vector3f::Zero();
    // world = orientation * local (rotation matrix, orthonormal columns).
    Eigen::Matrix3f orientation = Eigen::Matrix3f::Identity();
    bool valid = false;

    bool contains(const Eigen::Vector3f& p) const {
        if (!valid) return false;
        const Eigen::Vector3f pl = orientation.transpose() * (p - center);
        // A small relative tolerance keeps exact-boundary points inclusive:
        // rotating the query into the local frame accumulates float error of
        // order 1e-7 * extent, which otherwise drops points sitting exactly on
        // the box faces (visible e.g. after a 90-degree rotation).
        const float tol =
            std::max(1e-3f, 1e-4f * (max - min).cwiseAbs().maxCoeff());
        return (pl.array() >= (min.array() - tol)).all() &&
               (pl.array() <= (max.array() + tol)).all();
    }

    // Local extents (max - min, mm). For an axis-aligned box these equal the
    // world-space sizes.
    Eigen::Vector3f size() const { return max - min; }
};

}  // namespace pcsearch::core
