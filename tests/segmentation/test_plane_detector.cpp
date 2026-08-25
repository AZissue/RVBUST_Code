#include "pcsearch/core_data/point_cloud.h"
#include "pcsearch/segmentation/plane_detector.h"

#include <cmath>
#include <cstdlib>
#include <iostream>

namespace {

using pcsearch::core::LengthUnit;
using pcsearch::core::PointCloudData;
using pcsearch::core::Region;
using pcsearch::segmentation::PlaneParams;
using pcsearch::segmentation::detectPlanes;

bool nearlyEqual(double a, double b, double tol) {
    return std::abs(a - b) < tol;
}

PointCloudData makeSyntheticCloud() {
    // Three planes in mm:
    //  P1: z = 0      (normal 0,0,1)
    //  P2: y = 200    (normal 0,1,0)
    //  P3: x = -300   (normal -1,0,0)  -> detected normal may be +x or -x
    PointCloudData cloud;
    cloud.unit = LengthUnit::Millimeter;
    const int side = 50;
    cloud.points.resize(3LL * side * side, 3);
    std::int64_t row = 0;
    for (int i = 0; i < side; ++i) {
        for (int j = 0; j < side; ++j) {
            cloud.points(row, 0) = static_cast<float>(i);
            cloud.points(row, 1) = static_cast<float>(j);
            cloud.points(row, 2) = 0.0f;
            ++row;
        }
    }
    for (int i = 0; i < side; ++i) {
        for (int j = 0; j < side; ++j) {
            cloud.points(row, 0) = static_cast<float>(i);
            cloud.points(row, 1) = 200.0f;
            cloud.points(row, 2) = static_cast<float>(j);
            ++row;
        }
    }
    for (int i = 0; i < side; ++i) {
        for (int j = 0; j < side; ++j) {
            cloud.points(row, 0) = -300.0f;
            cloud.points(row, 1) = static_cast<float>(i);
            cloud.points(row, 2) = static_cast<float>(j);
            ++row;
        }
    }
    // Small noise so RANSAC still works but the test is not trivial.
    for (std::int64_t r = 0; r < cloud.size(); ++r) {
        const float n = (static_cast<float>(std::rand()) / RAND_MAX - 0.5f) * 0.05f;
        cloud.points(r, 0) += n;
        cloud.points(r, 1) += n;
        cloud.points(r, 2) += n;
    }
    return cloud;
}

int checkNormal(const std::vector<double>& params, double nx, double ny, double nz,
                double tol) {
    const double a = params[0];
    const double b = params[1];
    const double c = params[2];
    return (nearlyEqual(std::abs(a), std::abs(nx), tol) &&
            nearlyEqual(std::abs(b), std::abs(ny), tol) &&
            nearlyEqual(std::abs(c), std::abs(nz), tol))
               ? 0
               : 1;
}

}  // namespace

int main() {
    const PointCloudData cloud = makeSyntheticCloud();
    PlaneParams params;
    params.distance_threshold_mm = 0.5;
    params.min_inliers = 100;
    params.max_planes = 5;
    params.ransac_iterations = 2000;

    const auto planes = detectPlanes(cloud, params);

    std::cout << "detected " << planes.size() << " planes\n";
    int failures = 0;
    if (planes.size() < 3) {
        std::cerr << "FAIL: expected >= 3 planes, got " << planes.size() << "\n";
        return 1;
    }

    bool found_z = false;
    bool found_y = false;
    bool found_x = false;
    for (const auto& p : planes) {
        if (checkNormal(p.params, 0.0, 0.0, 1.0, 0.05) == 0) found_z = true;
        if (checkNormal(p.params, 0.0, 1.0, 0.0, 0.05) == 0) found_y = true;
        if (checkNormal(p.params, 1.0, 0.0, 0.0, 0.05) == 0) found_x = true;
        if (p.pointCount() < params.min_inliers) {
            std::cerr << "FAIL: plane " << p.id << " has too few points: "
                      << p.pointCount() << "\n";
            ++failures;
        }
    }
    if (!found_z) { std::cerr << "FAIL: z=0 plane not found\n"; ++failures; }
    if (!found_y) { std::cerr << "FAIL: y=200 plane not found\n"; ++failures; }
    if (!found_x) { std::cerr << "FAIL: x=-300 plane not found\n"; ++failures; }

    if (failures == 0) {
        std::cout << "PASS\n";
        return 0;
    }
    return 1;
}
