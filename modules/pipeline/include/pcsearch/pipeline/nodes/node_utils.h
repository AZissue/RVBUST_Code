#pragma once

#include "pcsearch/core_data/object.h"

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace pcsearch::pipeline {

// Map local output-row indices back through the object's source map.
inline std::vector<std::int64_t> composeIndices(
    const core::PointCloudObject& obj,
    const std::vector<std::int64_t>& local_indices) {
    if (!obj.source_indices.empty()) {
        std::vector<std::int64_t> out;
        out.reserve(local_indices.size());
        for (const auto i : local_indices) {
            out.push_back(obj.source_indices[static_cast<std::size_t>(i)]);
        }
        return out;
    }
    return local_indices;
}

// Build a top-level object (identity source map) from raw cloud data.
inline std::shared_ptr<core::PointCloudObject> makeObject(
    const core::PointCloudData& cloud, const std::string& id,
    const std::string& provenance) {
    auto obj = std::make_shared<core::PointCloudObject>();
    obj->id = id;
    obj->name = id;
    obj->cloud = std::make_shared<core::PointCloudData>(cloud);
    obj->source_indices.resize(static_cast<std::size_t>(cloud.size()));
    for (std::int64_t i = 0; i < cloud.size(); ++i) {
        obj->source_indices[static_cast<std::size_t>(i)] = i;
    }
    obj->provenance = provenance;
    core::Region all;
    all.id = "all";
    all.label = "all";
    all.kind = core::Region::Kind::All;
    all.indices = obj->source_indices;
    all.provenance = provenance;
    obj->regions.push_back(std::move(all));
    return obj;
}

// 1:1 filter helper: transform each object, keeping display metadata.
inline std::shared_ptr<core::PointCloudObject> transformObject(
    const core::PointCloudObject& src, core::PointCloudData cloud,
    const std::vector<std::int64_t>& local_indices,
    const std::string& provenance) {
    auto out = std::make_shared<core::PointCloudObject>();
    out->id = src.id;
    out->name = src.name;
    out->cloud = std::make_shared<core::PointCloudData>(std::move(cloud));
    out->source_indices = composeIndices(src, local_indices);
    out->visible = src.visible;
    out->display_color = src.display_color;
    out->provenance = provenance;
    return out;
}

// Copy rows [indices] of `src` into a new object; the region stored on the new
// object uses identity indices (0..k-1), while source_indices keeps the link
// back to the original file-level points.
inline std::shared_ptr<core::PointCloudObject> makeSubsetObject(
    const core::PointCloudObject& src, const std::vector<std::int64_t>& indices,
    const std::string& label, core::Region::Kind kind = core::Region::Kind::Manual,
    std::vector<double> params = {}, const std::string& provenance = {}) {
    auto out = std::make_shared<core::PointCloudObject>();
    out->id = src.id + "." + label;
    out->name = label;
    out->display_color = src.display_color;
    out->visible = src.visible;
    out->provenance = provenance;

    auto cloud = std::make_shared<core::PointCloudData>();
    cloud->unit = src.cloud->unit;
    cloud->source_path = src.cloud->source_path;
    cloud->frame_id = src.cloud->frame_id;
    cloud->points.resize(static_cast<std::int64_t>(indices.size()), 3);
    if (src.cloud->hasColors()) cloud->colors.resize(cloud->size(), 3);
    if (src.cloud->hasNormals()) cloud->normals.resize(cloud->size(), 3);
    for (std::int64_t k = 0; k < static_cast<std::int64_t>(indices.size()); ++k) {
        const std::int64_t i = indices[static_cast<std::size_t>(k)];
        cloud->points.row(k) = src.cloud->points.row(i);
        if (src.cloud->hasColors()) cloud->colors.row(k) = src.cloud->colors.row(i);
        if (src.cloud->hasNormals()) cloud->normals.row(k) = src.cloud->normals.row(i);
    }
    out->cloud = cloud;

    core::Region region;
    region.id = label;
    region.label = label;
    region.kind = kind;
    region.params = std::move(params);
    region.indices.resize(indices.size());
    for (std::int64_t k = 0; k < static_cast<std::int64_t>(indices.size()); ++k) {
        region.indices[static_cast<std::size_t>(k)] = k;
    }
    region.provenance = provenance;
    out->regions.push_back(std::move(region));

    out->source_indices = composeIndices(src, indices);
    return out;
}

}  // namespace pcsearch::pipeline
