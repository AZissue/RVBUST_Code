#include "pcsearch/clustering/clustering.h"

#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <pcl/search/kdtree.h>
#include <pcl/segmentation/extract_clusters.h>

#include <algorithm>
#include <cstdint>
#include <vector>

namespace pcsearch::clustering {

namespace {

using core::PointCloudData;
using core::Region;

pcl::PointCloud<pcl::PointXYZ>::Ptr toPclCloud(const PointCloudData& cloud) {
    auto out = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    out->resize(cloud.size());
    for (std::int64_t i = 0; i < cloud.size(); ++i) {
        (*out)[i].x = cloud.points(i, 0);
        (*out)[i].y = cloud.points(i, 1);
        (*out)[i].z = cloud.points(i, 2);
    }
    return out;
}

Region makeRegion(int id, std::vector<std::int64_t> indices) {
    Region r;
    r.id = "cluster_" + std::to_string(id);
    r.label = r.id;
    r.kind = Region::Kind::Cluster;
    r.indices = std::move(indices);
    return r;
}

}  // namespace

std::vector<Region> dbscan(const PointCloudData& cloud, const DbscanParams& params,
                           std::vector<std::int64_t>* noise) {
    std::vector<Region> result;
    if (noise) noise->clear();
    const std::int64_t n = cloud.size();
    if (n == 0) return result;

    const auto pcl_cloud = toPclCloud(cloud);
    pcl::KdTreeFLANN<pcl::PointXYZ> tree;
    tree.setInputCloud(pcl_cloud);

    std::vector<int> label(static_cast<std::size_t>(n), -1);
    std::vector<int> stack;
    stack.reserve(1024);
    int cluster_id = 0;

    for (std::int64_t i = 0; i < n; ++i) {
        if (label[static_cast<std::size_t>(i)] != -1) continue;
        std::vector<int> nbrs;
        std::vector<float> dists;
        tree.radiusSearch(static_cast<int>(i), static_cast<float>(params.eps_mm), nbrs,
                          dists);
        if (nbrs.size() < static_cast<std::size_t>(params.min_points)) {
            label[static_cast<std::size_t>(i)] = -2;
            continue;
        }

        const int cid = cluster_id++;
        label[static_cast<std::size_t>(i)] = cid;
        stack.clear();
        stack.insert(stack.end(), nbrs.begin(), nbrs.end());
        while (!stack.empty()) {
            const int j = stack.back();
            stack.pop_back();
            auto& lj = label[static_cast<std::size_t>(j)];
            if (lj == -2) {          // noise point reached by a core point
                lj = cid;
                continue;
            }
            if (lj != -1) continue;
            lj = cid;
            std::vector<int> jnbrs;
            std::vector<float> jdists;
            tree.radiusSearch(j, static_cast<float>(params.eps_mm), jnbrs, jdists);
            if (jnbrs.size() >= static_cast<std::size_t>(params.min_points)) {
                stack.insert(stack.end(), jnbrs.begin(), jnbrs.end());
            }
        }
    }

    std::vector<std::vector<std::int64_t>> members(static_cast<std::size_t>(cluster_id));
    for (std::int64_t i = 0; i < n; ++i) {
        const int l = label[static_cast<std::size_t>(i)];
        if (l >= 0) {
            members[static_cast<std::size_t>(l)].push_back(i);
        } else if (l == -2 && noise) {
            noise->push_back(i);
        }
    }
    result.reserve(members.size());
    for (std::size_t c = 0; c < members.size(); ++c) {
        if (!members[c].empty()) {
            result.push_back(makeRegion(static_cast<int>(c), std::move(members[c])));
        }
    }
    return result;
}

std::vector<Region> euclideanClusters(const PointCloudData& cloud,
                                      const EuclideanParams& params) {
    std::vector<Region> result;
    if (cloud.size() == 0) return result;

    const auto pcl_cloud = toPclCloud(cloud);
    pcl::search::KdTree<pcl::PointXYZ>::Ptr tree(new pcl::search::KdTree<pcl::PointXYZ>);
    tree->setInputCloud(pcl_cloud);

    pcl::EuclideanClusterExtraction<pcl::PointXYZ> ec;
    ec.setClusterTolerance(params.tolerance_mm);
    ec.setMinClusterSize(params.min_cluster_size);
    ec.setMaxClusterSize(params.max_cluster_size);
    ec.setSearchMethod(tree);
    ec.setInputCloud(pcl_cloud);

    std::vector<pcl::PointIndices> clusters;
    ec.extract(clusters);
    result.reserve(clusters.size());
    int id = 0;
    for (const auto& cl : clusters) {
        std::vector<std::int64_t> idx;
        idx.reserve(cl.indices.size());
        for (const auto& v : cl.indices) {
            idx.push_back(static_cast<std::int64_t>(v));
        }
        result.push_back(makeRegion(id++, std::move(idx)));
    }
    return result;
}

}  // namespace pcsearch::clustering

