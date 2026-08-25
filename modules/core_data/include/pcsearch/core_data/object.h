#pragma once

#include "pcsearch/core_data/point_cloud.h"
#include "pcsearch/core_data/region.h"
#include "pcsearch/core_data/roi.h"

#include <Eigen/Core>

#include <memory>
#include <string>
#include <vector>

namespace pcsearch::core {

// One processed point cloud object flowing through the pipeline.
// source_indices maps each row of `cloud->points` back to the original
// file-level point (identity mapping when the object starts as a whole file).
struct PointCloudObject {
    std::string id;
    std::string name;
    std::shared_ptr<PointCloudData> cloud;
    std::vector<Region> regions;
    std::shared_ptr<RoiBox> roi;  // optional axis-aligned ROI attached to this object
    std::vector<std::int64_t> source_indices;
    bool visible = true;
    Eigen::Vector3f display_color{0.7f, 0.7f, 0.7f};
    std::string provenance;  // node id that produced this object

    bool hasSourceMap() const {
        return !source_indices.empty() &&
               static_cast<std::int64_t>(source_indices.size()) == cloud->size();
    }
};

// The uniform in/out type of every node: a list of point cloud objects.
struct ObjectList {
    std::vector<std::shared_ptr<PointCloudObject>> objects;

    std::int64_t size() const { return static_cast<std::int64_t>(objects.size()); }
    bool empty() const { return objects.empty(); }
};

}  // namespace pcsearch::core
