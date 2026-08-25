#include "pcsearch/clustering/clustering.h"

#include <cmath>
#include <cstdint>
#include <iostream>
#include <random>
#include <vector>

namespace {

using pcsearch::core::PointCloudData;
using pcsearch::clustering::DbscanParams;
using pcsearch::clustering::EuclideanParams;
using pcsearch::clustering::dbscan;
using pcsearch::clustering::euclideanClusters;

int check(bool ok, const char* msg) {
    if (!ok) {
        std::cerr << "FAIL: " << msg << "\n";
        return 1;
    }
    return 0;
}

// Three separated blobs (5x5x5 boxes) plus a few far-away noise points.
PointCloudData makeCloud() {
    PointCloudData c;
    const std::int64_t per_blob = 200;
    c.points.resize(3 * per_blob + 8, 3);
    std::mt19937 rng(7);
    std::uniform_real_distribution<float> d(-2.5f, 2.5f);
    const float centers[3][3] = {{0.f, 0.f, 0.f}, {100.f, 0.f, 0.f}, {0.f, 100.f, 0.f}};
    std::int64_t r = 0;
    for (int b = 0; b < 3; ++b) {
        for (std::int64_t i = 0; i < per_blob; ++i) {
            c.points(r, 0) = centers[b][0] + d(rng);
            c.points(r, 1) = centers[b][1] + d(rng);
            c.points(r, 2) = centers[b][2] + d(rng);
            ++r;
        }
    }
    const float noise_centers[8][3] = {
        {500.f, 500.f, 500.f}, {510.f, 500.f, 500.f}, {500.f, 520.f, 500.f},
        {520.f, 500.f, 500.f}, {505.f, 505.f, 505.f}, {515.f, 515.f, 500.f},
        {500.f, 510.f, 510.f}, {530.f, 500.f, 500.f}};
    for (int i = 0; i < 8; ++i) {
        c.points(r, 0) = noise_centers[i][0];
        c.points(r, 1) = noise_centers[i][1];
        c.points(r, 2) = noise_centers[i][2];
        ++r;
    }
    return c;
}

}  // namespace

int main() {
    int failures = 0;
    const PointCloudData cloud = makeCloud();

    DbscanParams dp;
    dp.eps_mm = 10.0;
    dp.min_points = 20;
    std::vector<std::int64_t> noise;
    const auto dclusters = dbscan(cloud, dp, &noise);
    failures += check(dclusters.size() == 3, "dbscan: expected 3 clusters");
    failures += check(noise.size() == 8, "dbscan: expected 8 noise points");
    if (dclusters.size() == 3) {
        for (const auto& c : dclusters) {
            failures += check(c.pointCount() == 200, "dbscan: cluster size");
        }
    }

    EuclideanParams ep;
    ep.tolerance_mm = 10.0;
    ep.min_cluster_size = 50;
    const auto eclusters = euclideanClusters(cloud, ep);
    failures += check(eclusters.size() == 3, "euclidean: expected 3 clusters");
    if (eclusters.size() == 3) {
        for (const auto& c : eclusters) {
            failures += check(c.pointCount() == 200, "euclidean: cluster size");
        }
    }

    if (failures == 0) {
        std::cout << "PASS\n";
        return 0;
    }
    std::cerr << failures << " checks failed\n";
    return 1;
}
