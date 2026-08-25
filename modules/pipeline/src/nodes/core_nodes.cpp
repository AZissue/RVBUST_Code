#include "pcsearch/pipeline/nodes/core_nodes.h"

#include "pcsearch/clustering/clustering.h"
#include "pcsearch/filters/filters.h"
#include "pcsearch/io/point_cloud_io.h"
#include "pcsearch/pipeline/nodes/node_utils.h"
#include "pcsearch/pipeline/registry.h"
#include "pcsearch/segmentation/plane_detector.h"

#include <Eigen/Geometry>

#include <cmath>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

namespace pcsearch::pipeline {

namespace {

using core::ObjectList;
using core::PointCloudObject;
using filters::FilterResult;

constexpr double kDegToRad = 3.14159265358979323846 / 180.0;

// Build the world <- local rotation matrix from XYZ intrinsic Euler angles
// (degrees): R = Rz(rz) * Ry(ry) * Rx(rx). Must match the extraction used by
// the interactive ROI selector (app/roi_selector.cpp).
Eigen::Matrix3f eulerXYZDegToMatrix(const Eigen::Vector3f& r_deg) {
    const double rx = r_deg.x() * kDegToRad;
    const double ry = r_deg.y() * kDegToRad;
    const double rz = r_deg.z() * kDegToRad;
    const Eigen::Matrix3f r =
        (Eigen::AngleAxisf(static_cast<float>(rz), Eigen::Vector3f::UnitZ()) *
         Eigen::AngleAxisf(static_cast<float>(ry), Eigen::Vector3f::UnitY()) *
         Eigen::AngleAxisf(static_cast<float>(rx), Eigen::Vector3f::UnitX()))
            .toRotationMatrix();
    return r;
}

ParamDef doubleParam(const std::string& name, const std::string& label,
                     double dflt, double dmin, double dmax, const std::string& unit = {}) {
    ParamDef d;
    d.name = name;
    d.type = ParamType::Double;
    d.label = label;
    d.unit = unit;
    d.dmin = dmin;
    d.dmax = dmax;
    d.default_value = dflt;
    d.description = "default: " + std::to_string(dflt);
    return d;
}

ParamDef intParam(const std::string& name, const std::string& label, int dflt,
                  int imin, int imax) {
    ParamDef d;
    d.name = name;
    d.type = ParamType::Int;
    d.label = label;
    d.imin = imin;
    d.imax = imax;
    d.default_value = dflt;
    d.description = "default: " + std::to_string(dflt);
    return d;
}

ParamDef enumParam(const std::string& name, const std::string& label,
                   std::vector<std::string> values) {
    ParamDef d;
    d.name = name;
    d.type = ParamType::Enum;
    d.label = label;
    d.enum_values = std::move(values);
    if (!d.enum_values.empty()) d.default_value = d.enum_values.front();
    return d;
}

ParamDef stringParam(const std::string& name, const std::string& label) {
    ParamDef d;
    d.name = name;
    d.type = ParamType::String;
    d.label = label;
    d.default_value = std::string{};
    return d;
}

ParamDef stringParam(const std::string& name, const std::string& label,
                     const std::string& dflt) {
    ParamDef d;
    d.name = name;
    d.type = ParamType::String;
    d.label = label;
    d.default_value = dflt;
    return d;
}

ParamDef fileParam(const std::string& name, const std::string& label) {
    ParamDef d;
    d.name = name;
    d.type = ParamType::File;
    d.label = label;
    d.default_value = std::string{};
    return d;
}

ParamDef dirParam(const std::string& name, const std::string& label) {
    ParamDef d;
    d.name = name;
    d.type = ParamType::Directory;
    d.label = label;
    d.default_value = std::string{};
    return d;
}

// Defaults for enum params are the first value, so put the recommended
// value first in the list.
std::vector<ParamDef> makeLoadParams() {
    return {fileParam("path", "File Path"),
            dirParam("folder", "Batch Folder"),
            // stream = K=1 (default, one frame per graph run), chunked = K=10
            // configurable, all = K=N (whole folder in one run).
            enumParam("mode", "Read Mode", {"stream", "chunked", "all"}),
            intParam("chunk_size", "Chunk Size", 10, 1, 1000000),
            enumParam("source_unit", "Source Unit", {"auto", "meter", "millimeter"})};
}

core::LengthUnit resolveUnit(const std::string& unit) {
    if (unit == "millimeter") return core::LengthUnit::Millimeter;
    return core::LengthUnit::Meter;
}

std::string expandPath(const std::string& path, std::size_t index, std::size_t total) {
    if (total <= 1) return path;
    const std::filesystem::path p(path);
    return (p.parent_path() / (p.stem().string() + "_" + std::to_string(index) + p.extension().string()))
        .string();
}

// Zero-padded frame identity used for batch object ids / save naming:
// frame_000, frame_001, ... (PROJECT §8.5 / §9).
std::string frameName(std::int64_t index) {
    std::string s = std::to_string(index);
    if (s.size() < 3) s.insert(s.begin(), static_cast<std::string::size_type>(3 - s.size()), '0');
    return "frame_" + s;
}

}  // namespace

// ---------------------------------------------------------------------------
// LoadCloudNode
// ---------------------------------------------------------------------------

std::vector<ParamDef> LoadCloudNode::paramDefs() const { return makeLoadParams(); }

ObjectList LoadCloudNode::execute(const std::vector<ObjectList>&, const Params& p) {
    io::ReadOptions options;
    const std::string unit = p.getEnum("source_unit");
    if (unit != "auto") options.source_unit = resolveUnit(unit);

    const std::string folder = p.getString("folder");
    if (!folder.empty()) {
        // Batch folder: read the window injected by the engine, or everything
        // when no window is active (mode=all / single pass).
        std::vector<std::string> files = io::listPointCloudFiles(folder);
        if (files.empty()) return {};  // empty folder -> empty output (8.3.4)
        std::int64_t begin = 0;
        // Windowed reads apply only when this node drives batch execution
        // (stream/chunked mode); mode=all ignores the engine window.
        if (batchEnabled() && context().batch_count > 0) {
            begin = context().batch_start;
            const std::int64_t end = std::min(
                static_cast<std::int64_t>(files.size()),
                begin + context().batch_count);
            if (begin >= static_cast<std::int64_t>(files.size())) return {};
            files = std::vector<std::string>(files.begin() + begin, files.begin() + end);
        }
        ObjectList out;
        out.objects.reserve(files.size());
        for (std::size_t i = 0; i < files.size(); ++i) {
            const std::int64_t global = begin + static_cast<std::int64_t>(i);
            const std::string file = files[i];
            try {
                core::PointCloudData cloud = io::readPointCloud(file, options);
                const std::string fid = frameName(global);
                auto obj = makeObject(cloud, fid, id());
                obj->name = fid;
                out.objects.push_back(std::move(obj));
            } catch (const io::IoError& e) {
                throw std::runtime_error("load_cloud: frame " + frameName(global) +
                                         " failed: " + e.what());
            }
        }
        return out;
    }

    const std::string path = p.getString("path");
    if (path.empty()) throw std::runtime_error("load_cloud: no file path or folder set");
    core::PointCloudData cloud = io::readPointCloud(path, options);
    ObjectList out;
    out.objects.push_back(makeObject(cloud, "cloud", id()));
    return out;
}

bool LoadCloudNode::batchEnabled() const {
    return !params().getString("folder").empty() &&
           params().getEnum("mode") != "all";
}

std::int64_t LoadCloudNode::batchChunkSize() const {
    if (params().getEnum("mode") != "chunked") return 1;  // stream = K=1
    return std::max<std::int64_t>(1, params().getInt("chunk_size"));
}

std::int64_t LoadCloudNode::batchTotal() const {
    const std::string folder = params().getString("folder");
    if (!folder.empty()) {
        return static_cast<std::int64_t>(io::listPointCloudFiles(folder).size());
    }
    return params().getString("path").empty() ? 0 : 1;
}

// ---------------------------------------------------------------------------
// SaveCloudNode
// ---------------------------------------------------------------------------

std::vector<ParamDef> SaveCloudNode::paramDefs() const {
    return {dirParam("folder", "Output Folder"),
            stringParam("file_name", "File Name", "cloud"),
            enumParam("format", "Format", {"auto", "pcd", "ply", "xyz", "csv"}),
            enumParam("target_unit", "Output Unit", {"millimeter", "meter"})};
}

ObjectList SaveCloudNode::execute(const std::vector<ObjectList>& inputs, const Params& p) {
    if (inputs.empty() || inputs[0].objects.empty()) {
        return {};  // empty input propagates as empty output (8.3.4)
    }
    const std::string folder = p.getString("folder");
    if (folder.empty()) throw std::runtime_error("save_cloud: no output folder set");
    std::string file_name = p.getString("file_name");
    if (file_name.empty()) throw std::runtime_error("save_cloud: no file name set");

    io::WriteOptions options;
    const std::string fmt = p.getEnum("format");
    options.target_unit = resolveUnit(p.getEnum("target_unit"));
    io::Format format = io::Format::Auto;
    if (fmt == "pcd") format = io::Format::Pcd;
    else if (fmt == "ply") format = io::Format::Ply;
    else if (fmt == "xyz") format = io::Format::Xyz;
    else if (fmt == "csv") format = io::Format::Csv;

    // Format fallback: "auto" -> PLY (keeps colors, binary). The extension is
    // derived from the resolved format, so the user only picks a folder + name.
    if (format == io::Format::Auto) format = io::Format::Ply;
    const char* ext = format == io::Format::Pcd  ? ".pcd"
                      : format == io::Format::Xyz ? ".xyz"
                      : format == io::Format::Csv ? ".csv"
                                                  : ".ply";
    bool has_known_ext = false;
    for (const char* e : {".pcd", ".ply", ".xyz", ".csv"}) {
        if (file_name.size() >= 4 &&
            file_name.compare(file_name.size() - 4, 4, e) == 0) {
            has_known_ext = true;
            break;
        }
    }
    if (!has_known_ext) file_name += ext;
    options.format = format;

    const std::filesystem::path base_path =
        std::filesystem::path(folder) / file_name;
    std::error_code ec;
    std::filesystem::create_directories(base_path.parent_path(), ec);
    if (ec) {
        throw std::runtime_error("save_cloud: cannot create folder: " + folder);
    }

    const auto& objects = inputs[0].objects;
    for (std::size_t i = 0; i < objects.size(); ++i) {
        io::writePointCloud(expandPath(base_path.string(), i, objects.size()),
                            *objects[i]->cloud, options);
    }
    return inputs[0];
}

// ---------------------------------------------------------------------------
// RemoveInvalidNode
// ---------------------------------------------------------------------------

ObjectList RemoveInvalidNode::execute(const std::vector<ObjectList>& inputs, const Params&) {
    ObjectList out;
    for (const auto& obj : inputs[0].objects) {
        const FilterResult fr = filters::removeInvalidPoints(*obj->cloud);
        out.objects.push_back(transformObject(*obj, std::move(fr.cloud), fr.source_indices));
    }
    return out;
}

// ---------------------------------------------------------------------------
// VoxelDownsampleNode
// ---------------------------------------------------------------------------

std::vector<ParamDef> VoxelDownsampleNode::paramDefs() const {
    return {doubleParam("leaf_size", "Leaf Size", 5.0, 0.01, 100000.0, "mm"),
            enumParam("mode", "Mode", {"centroid", "center"})};
}

ObjectList VoxelDownsampleNode::execute(const std::vector<ObjectList>& inputs,
                                        const Params& p) {
    const filters::VoxelMode mode =
        p.getEnum("mode") == "center" ? filters::VoxelMode::Center : filters::VoxelMode::Centroid;
    ObjectList out;
    for (const auto& obj : inputs[0].objects) {
        const FilterResult fr =
            filters::voxelDownsample(*obj->cloud, p.getDouble("leaf_size"), mode);
        out.objects.push_back(transformObject(*obj, std::move(fr.cloud), fr.source_indices));
    }
    return out;
}

// ---------------------------------------------------------------------------
// RandomDownsampleNode
// ---------------------------------------------------------------------------

std::vector<ParamDef> RandomDownsampleNode::paramDefs() const {
    return {intParam("target_count", "Target Count", 100000, 1, 1000000000),
            intParam("seed", "Random Seed", 42, 0, 1000000)};
}

ObjectList RandomDownsampleNode::execute(const std::vector<ObjectList>& inputs,
                                         const Params& p) {
    ObjectList out;
    for (const auto& obj : inputs[0].objects) {
        const FilterResult fr = filters::randomDownsample(
            *obj->cloud, p.getInt("target_count"), static_cast<unsigned>(p.getInt("seed")));
        out.objects.push_back(transformObject(*obj, std::move(fr.cloud), fr.source_indices));
    }
    return out;
}

// ---------------------------------------------------------------------------
// ZFilterNode
// ---------------------------------------------------------------------------

std::vector<ParamDef> ZFilterNode::paramDefs() const {
    return {doubleParam("z_min", "Z Min", -1000.0, -1e9, 1e9, "mm"),
            doubleParam("z_max", "Z Max", 1000.0, -1e9, 1e9, "mm")};
}

ObjectList ZFilterNode::execute(const std::vector<ObjectList>& inputs, const Params& p) {
    ObjectList out;
    for (const auto& obj : inputs[0].objects) {
        const FilterResult fr = filters::filterByAxisRange(
            *obj->cloud, filters::Axis::Z, p.getDouble("z_min"), p.getDouble("z_max"));
        out.objects.push_back(transformObject(*obj, std::move(fr.cloud), fr.source_indices));
    }
    return out;
}

// ---------------------------------------------------------------------------
// ROI helpers
// ---------------------------------------------------------------------------

namespace {

// Keep the rows of `obj` that lie inside `box`, remap region indices to the
// new object layout, and attach the box to the output object.
std::shared_ptr<core::PointCloudObject> cropObject(
    const core::PointCloudObject& obj, const core::RoiBox& box) {
    const auto& cloud = *obj.cloud;
    const std::int64_t n = cloud.size();
    std::vector<std::int64_t> remap(static_cast<std::size_t>(n), -1);
    std::int64_t keep = 0;
    for (std::int64_t i = 0; i < n; ++i) {
        if (box.contains(cloud.points.row(i))) {
            remap[static_cast<std::size_t>(i)] = keep++;
        }
    }

    auto out = std::make_shared<core::PointCloudObject>();
    out->id = obj.id + ".roi";
    out->name = obj.name;
    out->display_color = obj.display_color;
    out->visible = obj.visible;
    out->provenance = obj.provenance;
    out->roi = std::make_shared<core::RoiBox>(box);

    auto cropped = std::make_shared<core::PointCloudData>();
    cropped->unit = cloud.unit;
    cropped->source_path = cloud.source_path;
    cropped->frame_id = cloud.frame_id;
    cropped->points.resize(keep, 3);
    if (cloud.hasColors()) cropped->colors.resize(keep, 3);
    if (cloud.hasNormals()) cropped->normals.resize(keep, 3);
    out->source_indices.resize(static_cast<std::size_t>(keep));
    std::int64_t r = 0;
    for (std::int64_t i = 0; i < n; ++i) {
        const std::int64_t j = remap[static_cast<std::size_t>(i)];
        if (j < 0) continue;
        cropped->points.row(j) = cloud.points.row(i);
        if (cloud.hasColors()) cropped->colors.row(j) = cloud.colors.row(i);
        if (cloud.hasNormals()) cropped->normals.row(j) = cloud.normals.row(i);
        out->source_indices[static_cast<std::size_t>(j)] =
            obj.source_indices.empty() ? i : obj.source_indices[static_cast<std::size_t>(i)];
        ++r;
    }
    out->cloud = cropped;

    for (const auto& region : obj.regions) {
        core::Region mapped = region;
        mapped.indices.clear();
        mapped.indices.reserve(region.indices.size());
        for (const auto idx : region.indices) {
            const std::int64_t j =
                idx >= 0 && idx < n ? remap[static_cast<std::size_t>(idx)] : -1;
            if (j >= 0) mapped.indices.push_back(j);
        }
        if (!mapped.indices.empty()) out->regions.push_back(std::move(mapped));
    }
    return out;
}

ObjectList cropByRoi(const ObjectList& input, const core::RoiBox& box) {
    ObjectList out;
    for (const auto& obj : input.objects) {
        out.objects.push_back(cropObject(*obj, box));
    }
    return out;
}

core::RoiBox boxFromParams(const Params& p) {
    core::RoiBox box;
    // xmin..zmax describe the box's extent around its center (mm). With zero
    // rotation they are exactly the world-space axis-aligned bounds; the
    // orientation rotates that box around the center.
    const Eigen::Vector3f mn(static_cast<float>(p.getDouble("xmin")),
                             static_cast<float>(p.getDouble("ymin")),
                             static_cast<float>(p.getDouble("zmin")));
    const Eigen::Vector3f mx(static_cast<float>(p.getDouble("xmax")),
                             static_cast<float>(p.getDouble("ymax")),
                             static_cast<float>(p.getDouble("zmax")));
    const Eigen::Vector3f half = 0.5f * (mx - mn);
    box.min = -half;
    box.max = half;
    box.center = 0.5f * (mn + mx);
    box.orientation = eulerXYZDegToMatrix(
        Eigen::Vector3f(static_cast<float>(p.getDouble("rot_x")),
                        static_cast<float>(p.getDouble("rot_y")),
                        static_cast<float>(p.getDouble("rot_z"))));
    box.valid = true;
    return box;
}

}  // namespace

// ---------------------------------------------------------------------------
// BoxRoiNode / RoiCropNode
// ---------------------------------------------------------------------------

std::vector<ParamDef> BoxRoiNode::paramDefs() const {
    return {doubleParam("xmin", "X Min", -100000.0, -1e9, 1e9, "mm"),
            doubleParam("xmax", "X Max", 100000.0, -1e9, 1e9, "mm"),
            doubleParam("ymin", "Y Min", -100000.0, -1e9, 1e9, "mm"),
            doubleParam("ymax", "Y Max", 100000.0, -1e9, 1e9, "mm"),
            doubleParam("zmin", "Z Min", -100000.0, -1e9, 1e9, "mm"),
            doubleParam("zmax", "Z Max", 100000.0, -1e9, 1e9, "mm"),
            doubleParam("rot_x", "Rotate X (deg)", 0.0, -360.0, 360.0),
            doubleParam("rot_y", "Rotate Y (deg)", 0.0, -360.0, 360.0),
            doubleParam("rot_z", "Rotate Z (deg)", 0.0, -360.0, 360.0)};
}

std::vector<ObjectList> BoxRoiNode::executeAll(const std::vector<ObjectList>& inputs,
                                               const Params& p) {
    const core::RoiBox box = boxFromParams(p);
    ObjectList cropped = cropByRoi(inputs[0], box);

    auto roi_obj = std::make_shared<core::PointCloudObject>();
    roi_obj->id = id() + ".roi";
    roi_obj->name = "roi";
    roi_obj->cloud = std::make_shared<core::PointCloudData>();
    roi_obj->roi = std::make_shared<core::RoiBox>(box);
    roi_obj->provenance = id();
    ObjectList roi_list;
    roi_list.objects.push_back(std::move(roi_obj));
    return {std::move(cropped), std::move(roi_list)};
}

ObjectList RoiCropNode::execute(const std::vector<ObjectList>& inputs, const Params&) {
    if (inputs.size() < 2 || inputs[1].objects.empty() ||
        !inputs[1].objects[0]->roi || !inputs[1].objects[0]->roi->valid) {
        // No ROI connected: pass the cloud through unchanged.
        return inputs.empty() ? ObjectList{} : inputs[0];
    }
    return cropByRoi(inputs[0], *inputs[1].objects[0]->roi);
}

// ---------------------------------------------------------------------------
// Display3DNode
// ---------------------------------------------------------------------------

std::vector<ParamDef> Display3DNode::paramDefs() const {
    return {stringParam("viewport", "Viewport")};
}

ObjectList Display3DNode::execute(const std::vector<ObjectList>& inputs, const Params&) {
    return inputs.empty() ? ObjectList{} : inputs[0];
}

void Display3DNode::setup() {
    Node::setup();
    params().set("viewport", ParamValue{std::string("Main")});
}

// ---------------------------------------------------------------------------
// PlaneDetectNode
// ---------------------------------------------------------------------------

std::vector<ParamDef> PlaneDetectNode::paramDefs() const {
    return {doubleParam("distance_threshold", "Distance Threshold", 1.0, 0.001, 100000.0,
                        "mm"),
            intParam("min_inliers", "Min Inliers", 100, 1, 1000000000),
            intParam("max_planes", "Max Planes", 10, 1, 1000),
            intParam("iterations", "RANSAC Iterations", 1000, 10, 1000000)};
}

ObjectList PlaneDetectNode::execute(const std::vector<ObjectList>& inputs, const Params& p) {
    segmentation::PlaneParams pp;
    pp.distance_threshold_mm = p.getDouble("distance_threshold");
    pp.min_inliers = p.getInt("min_inliers");
    pp.max_planes = p.getInt("max_planes");
    pp.ransac_iterations = p.getInt("iterations");
    ObjectList out;
    for (const auto& obj : inputs[0].objects) {
        const auto planes = segmentation::detectPlanes(*obj->cloud, pp);
        for (const auto& plane : planes) {
            out.objects.push_back(makeSubsetObject(*obj, plane.indices, plane.id,
                                                   core::Region::Kind::Plane, plane.params));
        }
    }
    return out;
}

// ---------------------------------------------------------------------------
// DbscanNode
// ---------------------------------------------------------------------------

std::vector<ParamDef> DbscanNode::paramDefs() const {
    return {doubleParam("eps", "Neighbor Radius (eps)", 5.0, 0.001, 100000.0, "mm"),
            intParam("min_points", "Min Points", 10, 1, 1000000)};
}

ObjectList DbscanNode::execute(const std::vector<ObjectList>& inputs, const Params& p) {
    clustering::DbscanParams dp;
    dp.eps_mm = p.getDouble("eps");
    dp.min_points = p.getInt("min_points");
    ObjectList out;
    for (const auto& obj : inputs[0].objects) {
        std::vector<std::int64_t> noise;
        const auto clusters = clustering::dbscan(*obj->cloud, dp, &noise);
        for (const auto& c : clusters) {
            out.objects.push_back(makeSubsetObject(*obj, c.indices, c.id,
                                                   core::Region::Kind::Cluster));
        }
        if (!noise.empty()) {
            out.objects.push_back(
                makeSubsetObject(*obj, noise, "noise", core::Region::Kind::Manual));
        }
    }
    return out;
}

// ---------------------------------------------------------------------------
// EuclideanClusterNode
// ---------------------------------------------------------------------------

std::vector<ParamDef> EuclideanClusterNode::paramDefs() const {
    return {doubleParam("tolerance", "Cluster Tolerance", 5.0, 0.001, 100000.0, "mm"),
            intParam("min_cluster_size", "Min Cluster Size", 50, 1, 1000000000),
            intParam("max_cluster_size", "Max Cluster Size", 100000, 1, 1000000000)};
}

ObjectList EuclideanClusterNode::execute(const std::vector<ObjectList>& inputs,
                                         const Params& p) {
    clustering::EuclideanParams ep;
    ep.tolerance_mm = p.getDouble("tolerance");
    ep.min_cluster_size = p.getInt("min_cluster_size");
    ep.max_cluster_size = p.getInt("max_cluster_size");
    ObjectList out;
    for (const auto& obj : inputs[0].objects) {
        const auto clusters = clustering::euclideanClusters(*obj->cloud, ep);
        for (const auto& c : clusters) {
            out.objects.push_back(makeSubsetObject(*obj, c.indices, c.id,
                                                   core::Region::Kind::Cluster));
        }
    }
    return out;
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

void registerCoreNodes() {
    NodeRegistry& r = NodeRegistry::instance();
    r.registerNode("load_cloud", "Load Cloud", "IO",
                   []() { return NodePtr(new LoadCloudNode("")); });
    r.registerNode("save_cloud", "Save Cloud", "IO",
                   []() { return NodePtr(new SaveCloudNode("")); });
    r.registerNode("remove_invalid", "Remove Invalid Points", "Filters",
                   []() { return NodePtr(new RemoveInvalidNode("")); });
    r.registerNode("voxel_downsample", "Voxel Downsample", "Filters",
                   []() { return NodePtr(new VoxelDownsampleNode("")); });
    r.registerNode("random_downsample", "Random Downsample", "Filters",
                   []() { return NodePtr(new RandomDownsampleNode("")); });
    r.registerNode("z_filter", "Z Range Filter", "Filters",
                   []() { return NodePtr(new ZFilterNode("")); });
    r.registerNode("box_roi", "Box ROI", "ROI",
                   []() { return NodePtr(new BoxRoiNode("")); });
    r.registerNode("roi_crop", "ROI Crop", "ROI",
                   []() { return NodePtr(new RoiCropNode("")); });
    r.registerNode("display3d", "Display 3D", "Display",
                   []() { return NodePtr(new Display3DNode("")); });
    r.registerNode("plane_detect", "Plane Detection", "Segmentation",
                   []() { return NodePtr(new PlaneDetectNode("")); });
    r.registerNode("dbscan", "DBSCAN Clustering", "Clustering",
                   []() { return NodePtr(new DbscanNode("")); });
    r.registerNode("euclidean_cluster", "Euclidean Clustering", "Clustering",
                   []() { return NodePtr(new EuclideanClusterNode("")); });
}

namespace {
struct CoreNodeRegistrar {
    CoreNodeRegistrar() { registerCoreNodes(); }
};
CoreNodeRegistrar core_node_registrar;
}  // namespace

}  // namespace pcsearch::pipeline
