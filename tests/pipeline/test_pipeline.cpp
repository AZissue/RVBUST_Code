#include "pcsearch/io/point_cloud_io.h"
#include "pcsearch/pipeline/graph.h"
#include "pcsearch/pipeline/json.h"
#include "pcsearch/pipeline/nodes/core_nodes.h"
#include "pcsearch/pipeline/solution.h"

#include <Eigen/Core>
#include <Eigen/Geometry>

#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <random>
#include <string>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#endif

namespace {

using pcsearch::core::PointCloudData;
using pcsearch::core::PointCloudObject;
using pcsearch::io::Format;
using pcsearch::io::writePointCloud;
using pcsearch::pipeline::Graph;
using pcsearch::pipeline::ParamValue;

int check(bool ok, const char* msg) {
    if (!ok) {
        std::cerr << "FAIL: " << msg << "\n";
        return 1;
    }
    return 0;
}

class RegionSinkNode final : public pcsearch::pipeline::Node {
public:
    using Node::Node;
    std::string type() const override { return "test_region_sink"; }
    std::string title() const override { return "Region Sink"; }
    std::string category() const override { return "Test"; }
    std::vector<pcsearch::pipeline::ParamDef> paramDefs() const override { return {}; }
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"region"}; }
    pcsearch::core::ObjectList execute(
        const std::vector<pcsearch::core::ObjectList>& inputs,
        const pcsearch::pipeline::Params&) override {
        return inputs.empty() ? pcsearch::core::ObjectList{} : inputs[0];
    }
};

class AnyPassthroughNode final : public pcsearch::pipeline::Node {
public:
    using Node::Node;
    std::string type() const override { return "test_any_passthrough"; }
    std::string title() const override { return "Any Passthrough"; }
    std::string category() const override { return "Test"; }
    std::vector<pcsearch::pipeline::ParamDef> paramDefs() const override { return {}; }
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"any"}; }
    std::vector<std::string> outputKinds() const override { return {"any"}; }
    pcsearch::core::ObjectList execute(
        const std::vector<pcsearch::core::ObjectList>& inputs,
        const pcsearch::pipeline::Params&) override {
        return inputs.empty() ? pcsearch::core::ObjectList{} : inputs[0];
    }
};

// Test-only sink that records the global frame index of every input object to
// a marker file (obj_<global>.txt). Used to verify that chunked batch
// execution visits every frame exactly once, in stable order.
class BatchSinkNode final : public pcsearch::pipeline::Node {
public:
    using Node::Node;
    std::string type() const override { return "test_batch_sink"; }
    std::string title() const override { return "Batch Sink"; }
    std::string category() const override { return "Test"; }
    std::vector<pcsearch::pipeline::ParamDef> paramDefs() const override {
        pcsearch::pipeline::ParamDef d;
        d.name = "out_dir";
        d.type = pcsearch::pipeline::ParamType::Directory;
        d.label = "Out Dir";
        d.default_value = std::string{};
        return {d};
    }
    std::size_t inputCount() const override { return 1; }
    std::vector<std::string> inputKinds() const override { return {"cloud"}; }
    pcsearch::core::ObjectList execute(
        const std::vector<pcsearch::core::ObjectList>& inputs,
        const pcsearch::pipeline::Params& p) override {
        const std::string out_dir = p.getString("out_dir");
        for (std::size_t i = 0; i < inputs[0].objects.size(); ++i) {
            const auto& obj = *inputs[0].objects[i];
            const std::int64_t global =
                context().batch_start + static_cast<std::int64_t>(i);
            std::ofstream out(std::filesystem::path(out_dir) /
                              ("obj_" + std::to_string(global) + ".txt"));
            out << obj.id << "\n" << obj.cloud->frame_id << "\n"
                << obj.cloud->size() << "\n";
        }
        return inputs[0];
    }
};

std::string writeTemp(const std::filesystem::path& dir, const std::string& name,
                      const PointCloudData& cloud) {
#ifdef _WIN32
    const int len = MultiByteToWideChar(CP_UTF8, 0, name.c_str(), -1, nullptr, 0);
    std::wstring wname(len > 0 ? static_cast<std::size_t>(len - 1) : 0, L'\0');
    if (len > 0) {
        MultiByteToWideChar(CP_UTF8, 0, name.c_str(), -1, wname.data(),
                            static_cast<int>(wname.size()));
    }
    const std::filesystem::path p = dir / wname;
    std::wstring wp = p.wstring();
    const int ulen = WideCharToMultiByte(CP_UTF8, 0, wp.c_str(), -1, nullptr, 0,
                                         nullptr, nullptr);
    std::string path(ulen > 0 ? static_cast<std::size_t>(ulen - 1) : 0, '\0');
    if (ulen > 0) {
        WideCharToMultiByte(CP_UTF8, 0, wp.c_str(), -1, path.data(), ulen,
                            nullptr, nullptr);
    }
#else
    const std::string path = (dir / name).string();
#endif
    writePointCloud(path, cloud);
    return path;
}

PointCloudData makeGridWithInvalid() {
    PointCloudData c;
    c.points.resize(10020, 3);
    std::int64_t r = 0;
    for (int i = 0; i < 100; ++i) {
        for (int j = 0; j < 100; ++j) {
            c.points(r, 0) = static_cast<float>(i);
            c.points(r, 1) = static_cast<float>(j);
            c.points(r, 2) = 0.0f;
            ++r;
        }
    }
    for (int k = 0; k < 20; ++k) {
        c.points(r, 0) = std::nanf("");
        c.points(r, 1) = 0.0f;
        c.points(r, 2) = 0.0f;
        ++r;
    }
    return c;
}

PointCloudData makeBlobs() {
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
    const float nc[8][3] = {{500.f, 500.f, 500.f}, {510.f, 500.f, 500.f},
                            {500.f, 520.f, 500.f}, {520.f, 500.f, 500.f},
                            {505.f, 505.f, 505.f}, {515.f, 515.f, 500.f},
                            {500.f, 510.f, 510.f}, {530.f, 500.f, 500.f}};
    for (int i = 0; i < 8; ++i) {
        c.points(r, 0) = nc[i][0];
        c.points(r, 1) = nc[i][1];
        c.points(r, 2) = nc[i][2];
        ++r;
    }
    return c;
}

PointCloudData makeLine(std::int64_t n, float z) {
    PointCloudData c;
    c.points.resize(n, 3);
    for (std::int64_t i = 0; i < n; ++i) {
        c.points(i, 0) = static_cast<float>(i);
        c.points(i, 1) = 0.0f;
        c.points(i, 2) = z;
    }
    return c;
}

}  // namespace

int main() {
    pcsearch::pipeline::registerCoreNodes();
    const std::filesystem::path dir =
        std::filesystem::temp_directory_path() / "pcsearch_pipeline_test";
    std::filesystem::create_directories(dir);
    int failures = 0;

    // ---- Chain: load -> remove invalid -> voxel ----
    {
        Graph g;
        const std::string grid_path = writeTemp(dir, "grid.ply", makeGridWithInvalid());
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{grid_path});
        auto* clean = g.addNode("remove_invalid");
        auto* vox = g.addNode("voxel_downsample");
        g.setParam(vox->id(), "leaf_size", ParamValue{10.0});
        g.connect(load->id(), 0, clean->id(), 0);
        g.connect(clean->id(), 0, vox->id(), 0);

        failures += check(g.execute(), "chain: execute ok");
        const auto stats_first = g.lastRunStats();
        failures += check(stats_first.count(load->id()) == 1 &&
                              stats_first.at(load->id()).executed &&
                              stats_first.at(load->id()).elapsed_ms >= 0.0,
                          "stats: load executed on first run");
        failures += check(stats_first.count(clean->id()) == 1 &&
                              stats_first.at(clean->id()).executed,
                          "stats: clean executed on first run");
        failures += check(stats_first.count(vox->id()) == 1 &&
                              stats_first.at(vox->id()).executed,
                          "stats: voxel executed on first run");
        const auto* load_out = g.output(load->id());
        const auto* clean_out = g.output(clean->id());
        const auto* vox_out = g.output(vox->id());
        failures += check(load_out && load_out->objects.size() == 1 &&
                              load_out->objects[0]->cloud->size() == 10020,
                          "chain: load count");
        failures += check(clean_out && clean_out->objects[0]->cloud->size() == 10000,
                          "chain: clean count");
        failures += check(vox_out && vox_out->objects[0]->cloud->size() == 100,
                          "chain: voxel count (leaf 10)");
        if (vox_out) {
            const auto& map = vox_out->objects[0]->source_indices;
            failures += check(static_cast<std::int64_t>(map.size()) ==
                                  vox_out->objects[0]->cloud->size(),
                              "chain: voxel source map size");
            bool in_range = true;
            for (const auto& s : map) in_range = in_range && s >= 0 && s < 10020;
            failures += check(in_range, "chain: voxel source map ranges");
        }

        // Dirty recompute: smaller leaf -> more voxels.
        g.setParam(vox->id(), "leaf_size", ParamValue{5.0});
        failures += check(g.execute(), "chain: re-execute ok");
        vox_out = g.output(vox->id());
        failures += check(vox_out && vox_out->objects[0]->cloud->size() == 400,
                          "chain: voxel count after param change (leaf 5)");

        // Second run only re-executed the dirty voxel node, load/clean skipped.
        const auto stats_second = g.lastRunStats();
        failures += check(stats_second.count(load->id()) == 1 &&
                              stats_second.at(load->id()).skipped,
                          "stats: load skipped on re-run");
        failures += check(stats_second.count(clean->id()) == 1 &&
                              stats_second.at(clean->id()).skipped,
                          "stats: clean skipped on re-run");
        failures += check(stats_second.count(vox->id()) == 1 &&
                              stats_second.at(vox->id()).executed,
                          "stats: voxel re-executed on re-run");
    }

    // ---- Z filter ----
    {
        Graph g;
        PointCloudData c;
        c.points.resize(101, 3);
        int expected = 0;
        for (std::int64_t i = 0; i < 101; ++i) {
            const float z = static_cast<float>((i * 7) % 21 - 10);  // -10..10
            c.points(i, 0) = 0.0f;
            c.points(i, 1) = 0.0f;
            c.points(i, 2) = z;
            if (z >= 0.0f && z <= 9.0f) ++expected;
        }
        const std::string path = writeTemp(dir, "z.ply", c);
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{path});
        auto* zf = g.addNode("z_filter");
        g.setParam(zf->id(), "z_min", ParamValue{0.0});
        g.setParam(zf->id(), "z_max", ParamValue{9.0});
        g.connect(load->id(), 0, zf->id(), 0);
        failures += check(g.execute(), "zfilter: execute ok");
        const auto* out = g.output(zf->id());
        failures += check(out && out->objects[0]->cloud->size() == expected,
                          "zfilter: count");
    }

    // ---- Box ROI + ROI crop chain ----
    {
        Graph g;
        const std::string path = writeTemp(dir, "roi_src.ply", makeGridWithInvalid());
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{path});
        auto* box = g.addNode("box_roi");
        g.setParam(box->id(), "xmin", ParamValue{25.0});
        g.setParam(box->id(), "xmax", ParamValue{49.0});
        g.setParam(box->id(), "ymin", ParamValue{25.0});
        g.setParam(box->id(), "ymax", ParamValue{49.0});
        g.setParam(box->id(), "zmin", ParamValue{-1.0});
        g.setParam(box->id(), "zmax", ParamValue{1.0});
        g.connect(load->id(), 0, box->id(), 0);
        failures += check(g.execute(), "roi: execute ok");

        const auto* cropped = g.output(box->id(), 0);
        failures += check(cropped && cropped->objects.size() == 1 &&
                              cropped->objects[0]->cloud->size() == 625,
                          "roi: cropped count 25x25");
        if (cropped) {
            const auto& map = cropped->objects[0]->source_indices;
            failures += check(static_cast<std::int64_t>(map.size()) == 625,
                              "roi: source map size");
            bool in_range = true;
            for (const auto& s : map) in_range = in_range && s >= 0 && s < 10020;
            failures += check(in_range, "roi: source map ranges");
            failures += check(cropped->objects[0]->roi &&
                                  cropped->objects[0]->roi->valid,
                              "roi: cropped object carries roi box");
        }
        const auto* roi_out = g.output(box->id(), 1);
        failures += check(roi_out && roi_out->objects.size() == 1 &&
                              roi_out->objects[0]->roi &&
                              roi_out->objects[0]->roi->valid,
                          "roi: region port carries roi object");

        // ROI crop consumes cloud + region ports.
        auto* crop = g.addNode("roi_crop");
        failures += check(g.canConnect(load->id(), 0, crop->id(), 0),
                          "roi: cloud -> crop input0 ok");
        failures += check(g.canConnect(box->id(), 1, crop->id(), 1),
                          "roi: region -> crop input1 ok");
        failures += check(!g.canConnect(box->id(), 1, crop->id(), 0),
                          "roi: region -> cloud input rejected");
        g.connect(load->id(), 0, crop->id(), 0);
        g.connect(box->id(), 1, crop->id(), 1);
        failures += check(g.execute(), "roi: crop execute ok");
        const auto* crop_out = g.output(crop->id());
        failures += check(crop_out && crop_out->objects.size() == 1 &&
                              crop_out->objects[0]->cloud->size() == 625,
                          "roi: crop output matches box_roi cropped count");
    }

    // ---- Oriented ROI (rotation) ----
    {
        // Direct contains() check: center (37,37,0), half (10,30,1), rotated
        // 90 deg about Z. Local +x points along world +y, so (10,30) is inside
        // while the transposed point (30,10) is outside.
        {
            using pcsearch::core::RoiBox;
            RoiBox box;
            box.min = Eigen::Vector3f(-10.0f, -30.0f, -1.0f);
            box.max = Eigen::Vector3f(10.0f, 30.0f, 1.0f);
            box.center = Eigen::Vector3f(37.0f, 37.0f, 0.0f);
            constexpr double kPi = 3.14159265358979323846;
            box.orientation =
                Eigen::AngleAxisf(static_cast<float>(90.0 * kPi / 180.0),
                                  Eigen::Vector3f::UnitZ())
                    .toRotationMatrix();
            box.valid = true;
            failures += check(box.contains(Eigen::Vector3f(10.0f, 30.0f, 0.0f)),
                              "roi_rot: contains rotated inside point");
            failures += check(!box.contains(Eigen::Vector3f(30.0f, 10.0f, 0.0f)),
                              "roi_rot: rejects transposed outside point");
            failures += check(box.contains(Eigen::Vector3f(37.0f, 37.0f, 0.5f)),
                              "roi_rot: contains center");
        }

        // Node-level: box_roi with rot_z=90 crops the transposed region of a
        // 100x100 grid: x in [7,67] (61) and y in [27,47] (21) -> 1281 points.
        {
            Graph g;
            const std::string path =
                writeTemp(dir, "roi_rot_src.ply", makeGridWithInvalid());
            auto* load = g.addNode("load_cloud");
            g.setParam(load->id(), "path", ParamValue{path});
            auto* box = g.addNode("box_roi");
            g.setParam(box->id(), "xmin", ParamValue{27.0});
            g.setParam(box->id(), "xmax", ParamValue{47.0});
            g.setParam(box->id(), "ymin", ParamValue{7.0});
            g.setParam(box->id(), "ymax", ParamValue{67.0});
            g.setParam(box->id(), "zmin", ParamValue{-1.0});
            g.setParam(box->id(), "zmax", ParamValue{1.0});
            g.setParam(box->id(), "rot_z", ParamValue{90.0});
            g.connect(load->id(), 0, box->id(), 0);
            failures += check(g.execute(), "roi_rot: execute ok");

            const auto* cropped = g.output(box->id(), 0);
            failures += check(cropped && cropped->objects.size() == 1 &&
                                  cropped->objects[0]->cloud->size() == 1281,
                              "roi_rot: cropped count (transposed 61x21)");
            if (cropped) {
                bool has_inside = false, has_outside = false;
                const auto& c = *cropped->objects[0]->cloud;
                for (std::int64_t i = 0; i < c.size(); ++i) {
                    const float x = c.points(i, 0), y = c.points(i, 1);
                    if (std::abs(x - 10.0f) < 1e-4f && std::abs(y - 30.0f) < 1e-4f) {
                        has_inside = true;
                    }
                    if (std::abs(x - 30.0f) < 1e-4f && std::abs(y - 10.0f) < 1e-4f) {
                        has_outside = true;
                    }
                }
                failures += check(has_inside, "roi_rot: includes (10,30)");
                failures += check(!has_outside, "roi_rot: excludes (30,10)");
            }
        }
    }

    // ---- DBSCAN ----
    {
        Graph g;
        const std::string path = writeTemp(dir, "blobs.ply", makeBlobs());
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{path});
        auto* db = g.addNode("dbscan");
        g.setParam(db->id(), "eps", ParamValue{10.0});
        g.setParam(db->id(), "min_points", ParamValue{20});
        g.connect(load->id(), 0, db->id(), 0);
        failures += check(g.execute(), "dbscan: execute ok");
        const auto* out = g.output(db->id());
        failures += check(out && out->objects.size() == 4,
                          "dbscan: 3 clusters + 1 noise object");
    }

    // ---- Random downsample node (E2E through graph) ----
    {
        Graph g;
        PointCloudData c;
        c.points.resize(500, 3);
        for (std::int64_t i = 0; i < 500; ++i) {
            c.points(i, 0) = static_cast<float>(i);
            c.points(i, 1) = 0.0f;
            c.points(i, 2) = 0.0f;
        }
        const std::string path = writeTemp(dir, "rand_src.ply", c);
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{path});
        auto* rnd = g.addNode("random_downsample");
        g.setParam(rnd->id(), "target_count", ParamValue{75});
        g.setParam(rnd->id(), "seed", ParamValue{99});
        g.connect(load->id(), 0, rnd->id(), 0);
        failures += check(g.execute(), "random: execute ok");
        const auto* out = g.output(rnd->id());
        failures += check(out && out->objects.size() == 1 &&
                              out->objects[0]->cloud->size() == 75,
                          "random: count");
        std::vector<std::int64_t> reference_map;
        if (out && !out->objects.empty()) {
            const auto& map = out->objects[0]->source_indices;
            reference_map = map;
            failures += check(static_cast<std::int64_t>(map.size()) == 75,
                              "random: source map size");
            bool in_range = true;
            for (const auto& s : map) in_range = in_range && s >= 0 && s < 500;
            failures += check(in_range, "random: source map ranges");
        }

        // Same seed reproduces the same subset (deterministic pipeline).
        Graph g2;
        auto* load2 = g2.addNode("load_cloud");
        g2.setParam(load2->id(), "path", ParamValue{path});
        auto* rnd2 = g2.addNode("random_downsample");
        g2.setParam(rnd2->id(), "target_count", ParamValue{75});
        g2.setParam(rnd2->id(), "seed", ParamValue{99});
        g2.connect(load2->id(), 0, rnd2->id(), 0);
        failures += check(g2.execute(), "random: re-run execute ok");
        const auto* out2 = g2.output(rnd2->id());
        failures += check(out2 && out2->objects.size() == 1 &&
                              out2->objects[0]->source_indices ==
                                  reference_map,
                          "random: deterministic with fixed seed");
    }

    // ---- Euclidean clustering node (E2E through graph) ----
    {
        Graph g;
        const std::string path = writeTemp(dir, "blobs_euclid.ply", makeBlobs());
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{path});
        auto* eu = g.addNode("euclidean_cluster");
        g.setParam(eu->id(), "tolerance", ParamValue{10.0});
        g.setParam(eu->id(), "min_cluster_size", ParamValue{50});
        g.connect(load->id(), 0, eu->id(), 0);
        failures += check(g.execute(), "euclidean: execute ok");
        const auto* out = g.output(eu->id());
        failures += check(out && out->objects.size() == 3,
                          "euclidean: 3 clusters (noise below min size dropped)");
        if (out) {
            for (const auto& obj : out->objects) {
                failures += check(static_cast<std::int64_t>(obj->source_indices.size()) ==
                                      obj->cloud->size(),
                                  "euclidean: source map size == cloud size");
                failures += check(!obj->regions.empty() &&
                                      obj->regions[0].kind ==
                                          pcsearch::core::Region::Kind::Cluster,
                                  "euclidean: region kind cluster");
                bool in_range = true;
                for (const auto& s : obj->source_indices)
                    in_range = in_range && s >= 0 && s < 608;
                failures += check(in_range, "euclidean: source map ranges");
            }
        }
    }

    // ---- Plane detection node (E2E through graph) ----
    {
        Graph g;
        constexpr int side = 50;
        PointCloudData c;
        c.points.resize(3LL * side * side, 3);
        std::int64_t row = 0;
        for (int i = 0; i < side; ++i) {
            for (int j = 0; j < side; ++j) {
                c.points(row, 0) = static_cast<float>(i);
                c.points(row, 1) = static_cast<float>(j);
                c.points(row, 2) = 0.0f;
                ++row;
            }
        }
        for (int i = 0; i < side; ++i) {
            for (int j = 0; j < side; ++j) {
                c.points(row, 0) = static_cast<float>(i);
                c.points(row, 1) = 200.0f;
                c.points(row, 2) = static_cast<float>(j);
                ++row;
            }
        }
        for (int i = 0; i < side; ++i) {
            for (int j = 0; j < side; ++j) {
                c.points(row, 0) = -300.0f;
                c.points(row, 1) = static_cast<float>(i);
                c.points(row, 2) = static_cast<float>(j);
                ++row;
            }
        }
        const std::string path = writeTemp(dir, "planes.ply", c);
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{path});
        auto* pd = g.addNode("plane_detect");
        g.setParam(pd->id(), "distance_threshold", ParamValue{0.5});
        g.setParam(pd->id(), "min_inliers", ParamValue{100});
        g.setParam(pd->id(), "max_planes", ParamValue{5});
        g.setParam(pd->id(), "iterations", ParamValue{2000});
        g.connect(load->id(), 0, pd->id(), 0);
        failures += check(g.execute(), "plane: execute ok");
        const auto* out = g.output(pd->id());
        failures += check(out && out->objects.size() >= 3,
                          "plane: at least 3 planes detected");
        if (out) {
            for (const auto& obj : out->objects) {
                failures += check(!obj->regions.empty() &&
                                      obj->regions[0].kind ==
                                          pcsearch::core::Region::Kind::Plane &&
                                      obj->regions[0].params.size() == 4,
                                  "plane: region kind plane + params [a,b,c,d]");
                failures += check(static_cast<std::int64_t>(obj->source_indices.size()) ==
                                      obj->cloud->size(),
                                  "plane: source map size == cloud size");
                bool in_range = true;
                for (const auto& s : obj->source_indices)
                    in_range = in_range && s >= 0 && s < 3LL * side * side;
                failures += check(in_range, "plane: source map ranges");
            }
        }
    }

    // ---- Cycle detection ----
    {
        Graph g;
        auto* a = g.addNode("z_filter");
        auto* b = g.addNode("z_filter");
        g.connect(a->id(), 0, b->id(), 0);
        g.connect(b->id(), 0, a->id(), 0);
        failures += check(!g.execute(), "cycle: execute must fail");
        failures += check(g.lastError().find("cycle") != std::string::npos,
                          "cycle: error mentions cycle");
    }

    // ---- Save passthrough ----
    {
        Graph g;
        const std::string path = writeTemp(dir, "save_src.ply", makeGridWithInvalid());
        const std::string out_folder = (dir / "save_out").string();
        const std::string out_path = out_folder + "/save_out.ply";
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{path});
        auto* save = g.addNode("save_cloud");
        g.setParam(save->id(), "folder", ParamValue{out_folder});
        g.setParam(save->id(), "file_name", ParamValue{std::string("save_out")});
        g.connect(load->id(), 0, save->id(), 0);
        failures += check(g.execute(), "save: execute ok");
        failures += check(std::filesystem::exists(out_path), "save: file written");
        const auto* out = g.output(save->id());
        failures += check(out && out->objects.size() == 1, "save: passthrough");
    }

    // ---- Save: folder auto-created, name gets .ply extension ----
    {
        Graph g;
        const std::string path = writeTemp(dir, "save_noext_src.ply", makeGridWithInvalid());
        // Nested folder that does not exist yet.
        const std::string out_folder =
            (dir / "nested" / "save_noext_out").string();
        const std::string expected = out_folder + "/1.ply";
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{path});
        auto* save = g.addNode("save_cloud");
        g.setParam(save->id(), "folder", ParamValue{out_folder});
        g.setParam(save->id(), "file_name", ParamValue{std::string("1")});
        g.connect(load->id(), 0, save->id(), 0);
        failures += check(g.execute(), "save_noext: execute ok (format auto)");
        failures += check(std::filesystem::exists(expected),
                          "save_noext: .ply appended");
    }

    // ---- Batch: load_cloud folder modes + chunked engine execution ----
    {
        pcsearch::pipeline::NodeRegistry::instance().registerNode(
            "test_batch_sink", "Batch Sink", "Test",
            [] { return std::make_unique<BatchSinkNode>(std::string{}); });

        const std::filesystem::path src_dir = dir / "batch_src";
        std::filesystem::create_directories(src_dir);
        // Natural file order must be shot_1 (10 pts), shot_2 (20), shot_10 (100).
        writeTemp(src_dir, "shot_2.ply", makeLine(20, 2.0f));
        writeTemp(src_dir, "shot_10.ply", makeLine(100, 10.0f));
        writeTemp(src_dir, "shot_1.ply", makeLine(10, 1.0f));

        // mode=all: whole folder in one pass, zero-padded ids, per-frame
        // identity source maps, frame_id = file stem.
        {
            Graph g;
            auto* load = g.addNode("load_cloud");
            g.setParam(load->id(), "folder", ParamValue{src_dir.string()});
            g.setParam(load->id(), "mode", ParamValue{std::string("all")});
            failures += check(!g.batchEnabled(), "batch: mode=all not batch-enabled");
            failures += check(g.execute(), "batch: all-mode execute ok");
            const auto* out = g.output(load->id());
            failures += check(out && out->objects.size() == 3,
                              "batch: all-mode object count");
            if (out && out->objects.size() == 3) {
                const std::string expect_ids[3] = {"frame_000", "frame_001", "frame_002"};
                const std::string expect_frames[3] = {"shot_1", "shot_2", "shot_10"};
                const std::int64_t expect_sizes[3] = {10, 20, 100};
                for (int i = 0; i < 3; ++i) {
                    const auto& obj = *out->objects[i];
                    failures += check(obj.id == expect_ids[i], "batch: all-mode id");
                    failures += check(obj.cloud->frame_id == expect_frames[i],
                                      "batch: all-mode frame_id");
                    failures += check(obj.cloud->size() == expect_sizes[i],
                                      "batch: all-mode size");
                    failures += check(static_cast<std::int64_t>(obj.source_indices.size()) ==
                                          obj.cloud->size(),
                                      "batch: source map size");
                    bool identity = true;
                    for (std::int64_t k = 0; k < obj.cloud->size(); ++k) {
                        identity = identity &&
                                   obj.source_indices[static_cast<std::size_t>(k)] == k;
                    }
                    failures += check(identity, "batch: per-frame identity source map");
                    failures += check(!obj.regions.empty(),
                                      "batch: object carries regions");
                }
            }
        }

        // stream (K=1) with a sink: every frame visited exactly once in the
        // same order as mode=all; only the last block's results are retained.
        {
            Graph g;
            auto* load = g.addNode("load_cloud");
            g.setParam(load->id(), "folder", ParamValue{src_dir.string()});
            g.setParam(load->id(), "mode", ParamValue{std::string("stream")});
            failures += check(g.batchEnabled(), "batch: stream batch-enabled");
            failures += check(g.batchChunkSize() == 1, "batch: stream chunk size 1");
            failures += check(load->batchTotal() == 3, "batch: total 3");

            const std::filesystem::path sink_dir = dir / "batch_stream_sink";
            std::filesystem::create_directories(sink_dir);
            auto* sink = g.addNode("test_batch_sink");
            g.setParam(sink->id(), "out_dir", ParamValue{sink_dir.string()});
            g.connect(load->id(), 0, sink->id(), 0);

            failures += check(g.executeChunked(1), "batch: stream execute ok");
            const auto* out = g.output(load->id());
            failures += check(out && out->objects.size() == 1 &&
                                  out->objects[0]->id == "frame_002",
                              "batch: last block kept (stream)");
            bool all_written = true;
            for (int i = 0; i < 3; ++i) {
                if (!std::filesystem::exists(sink_dir / ("obj_" + std::to_string(i) + ".txt"))) {
                    all_written = false;
                    break;
                }
            }
            failures += check(all_written, "batch: all frames streamed exactly once");
            std::ifstream m0(sink_dir / "obj_0.txt");
            std::string line;
            std::getline(m0, line);
            failures += check(line == "frame_000", "batch: sink id frame_000");
            std::getline(m0, line);
            failures += check(line == "shot_1", "batch: sink frame_id shot_1");
            std::getline(m0, line);
            failures += check(line == "10", "batch: sink size shot_1");
        }

        // chunked (K=2): one full block + one leftover frame.
        {
            Graph g;
            auto* load = g.addNode("load_cloud");
            g.setParam(load->id(), "folder", ParamValue{src_dir.string()});
            g.setParam(load->id(), "mode", ParamValue{std::string("chunked")});
            g.setParam(load->id(), "chunk_size", ParamValue{2});
            failures += check(g.batchEnabled(), "batch: chunked batch-enabled");
            failures += check(g.batchChunkSize() == 2, "batch: chunked chunk size 2");
            failures += check(g.executeChunked(2), "batch: chunked execute ok");
            const auto* out = g.output(load->id());
            failures += check(out && out->objects.size() == 1 &&
                                  out->objects[0]->id == "frame_002",
                              "batch: chunked leftover frame kept");
        }

        // K >= total: one block, whole batch returned.
        {
            Graph g;
            auto* load = g.addNode("load_cloud");
            g.setParam(load->id(), "folder", ParamValue{src_dir.string()});
            g.setParam(load->id(), "mode", ParamValue{std::string("stream")});
            failures += check(g.executeChunked(10), "batch: one-block execute ok");
            const auto* out = g.output(load->id());
            failures += check(out && out->objects.size() == 3,
                              "batch: one-block all frames");
        }

        // Empty folder: empty output propagates (no error), both modes.
        {
            const std::filesystem::path empty_dir = dir / "batch_empty";
            std::filesystem::create_directories(empty_dir);
            Graph g;
            auto* load = g.addNode("load_cloud");
            g.setParam(load->id(), "folder", ParamValue{empty_dir.string()});
            g.setParam(load->id(), "mode", ParamValue{std::string("all")});
            auto* save = g.addNode("save_cloud");
            g.setParam(save->id(), "folder",
                       ParamValue{(dir / "batch_empty_out").string()});
            g.setParam(save->id(), "file_name", ParamValue{std::string("empty")});
            g.connect(load->id(), 0, save->id(), 0);
            failures += check(g.execute(), "batch: empty folder execute ok");
            const auto* out = g.output(save->id());
            failures += check(out && out->objects.empty(),
                              "batch: empty propagates through save");
            failures += check(g.executeChunked(1), "batch: empty folder chunked ok");
        }

        // Single file: never batch-enabled even when mode=stream.
        {
            Graph g;
            auto* load = g.addNode("load_cloud");
            g.setParam(load->id(), "path",
                       ParamValue{writeTemp(src_dir, "single.ply", makeLine(7, 0.0f))});
            g.setParam(load->id(), "mode", ParamValue{std::string("stream")});
            failures += check(!g.batchEnabled(), "batch: single file not batch-enabled");
            failures += check(g.execute(), "batch: single file executes");
            const auto* out = g.output(load->id());
            failures += check(out && out->objects.size() == 1 &&
                                  out->objects[0]->id == "cloud",
                              "batch: single file id cloud");
        }
    }

    // ---- Multi-box box_roi: F x M cloud/region alignment + labels ----
    {
        const std::filesystem::path src_dir = dir / "mbbox_src";
        std::filesystem::create_directories(src_dir);
        writeTemp(src_dir, "f0.ply", makeLine(100, 0.0f));
        writeTemp(src_dir, "f1.ply", makeLine(80, 5.0f));

        Graph g;
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "folder", ParamValue{src_dir.string()});
        g.setParam(load->id(), "mode", ParamValue{std::string("all")});
        auto* box = g.addNode("box_roi");
        g.setParam(box->id(), "box_count", ParamValue{2});
        g.setParam(box->id(), "boxes_json",
                   ParamValue{std::string(
                       R"([{"xmin":-10,"xmax":49,"ymin":-10,"ymax":10,"zmin":-10,"zmax":10},)"
                       R"({"xmin":60,"xmax":110,"ymin":-10,"ymax":10,"zmin":-10,"zmax":10}])")});
        g.connect(load->id(), 0, box->id(), 0);
        failures += check(g.execute(), "mbbox: execute ok");

        const auto* clouds = g.output(box->id(), 0);
        const auto* regions = g.output(box->id(), 1);
        failures += check(clouds && regions && clouds->objects.size() == 4 &&
                              regions->objects.size() == 4,
                          "mbbox: F x M = 2x2 outputs");
        if (clouds && regions && clouds->objects.size() == 4) {
            const std::int64_t expect_counts[4] = {50, 40, 50, 20};
            const std::string expect_ids[4] = {"frame_000.roi0", "frame_000.roi1",
                                               "frame_001.roi0", "frame_001.roi1"};
            const std::string expect_labels[4] = {"roi0", "roi1", "roi0", "roi1"};
            for (int j = 0; j < 4; ++j) {
                const auto& c = *clouds->objects[j];
                const auto& r = *regions->objects[j];
                failures += check(c.id == expect_ids[j], "mbbox: cloud id");
                failures += check(r.id == expect_ids[j], "mbbox: region id");
                failures += check(c.cloud->size() == expect_counts[j],
                                  "mbbox: crop count");
                failures += check(c.roi && r.roi && c.roi->label == expect_labels[j] &&
                                      r.roi->label == expect_labels[j],
                                  "mbbox: roi label on cloud+region");
                failures += check(c.provenance == box->id() &&
                                      r.provenance == box->id(),
                                  "mbbox: provenance = box node");
                if (c.roi && r.roi) {
                    failures += check((c.roi->center - r.roi->center).norm() < 1e-4f &&
                                          (c.roi->min - r.roi->min).norm() < 1e-4f &&
                                          (c.roi->max - r.roi->max).norm() < 1e-4f,
                                      "mbbox: cloud.roi == region.roi");
                }
                // Source indices map back into the per-frame file.
                failures += check(static_cast<std::int64_t>(c.source_indices.size()) ==
                                      c.cloud->size(),
                                  "mbbox: source map size");
            }
        }

        // box_count > 1 without a box list is a node-level error (fail-fast).
        Graph g2;
        auto* load2 = g2.addNode("load_cloud");
        g2.setParam(load2->id(), "folder", ParamValue{src_dir.string()});
        g2.setParam(load2->id(), "mode", ParamValue{std::string("all")});
        auto* box2 = g2.addNode("box_roi");
        g2.setParam(box2->id(), "box_count", ParamValue{2});
        g2.connect(load2->id(), 0, box2->id(), 0);
        failures += check(!g2.execute(), "mbbox: missing box list must fail");
        failures += check(g2.lastError().find("boxes_json") != std::string::npos,
                          "mbbox: error mentions boxes_json");
    }

    // ---- Provenance is the producing node id (PROJECT §9) ----
    {
        Graph g;
        const std::string path = writeTemp(dir, "prov_src.ply", makeGridWithInvalid());
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{path});
        auto* clean = g.addNode("remove_invalid");
        g.connect(load->id(), 0, clean->id(), 0);
        failures += check(g.execute(), "prov: execute ok");
        const auto* out = g.output(clean->id());
        failures += check(out && out->objects.size() == 1 &&
                              out->objects[0]->provenance == clean->id(),
                          "prov: filter object provenance = node id");

        Graph g2;
        auto* load2 = g2.addNode("load_cloud");
        g2.setParam(load2->id(), "path", ParamValue{path});
        auto* box = g2.addNode("box_roi");
        g2.setParam(box->id(), "xmin", ParamValue{0.0});
        g2.setParam(box->id(), "xmax", ParamValue{49.0});
        g2.setParam(box->id(), "ymin", ParamValue{0.0});
        g2.setParam(box->id(), "ymax", ParamValue{49.0});
        g2.setParam(box->id(), "zmin", ParamValue{-1.0});
        g2.setParam(box->id(), "zmax", ParamValue{1.0});
        g2.connect(load2->id(), 0, box->id(), 0);
        failures += check(g2.execute(), "prov: box execute ok");
        const auto* cropped = g2.output(box->id(), 0);
        const auto* regions = g2.output(box->id(), 1);
        failures += check(cropped && regions && cropped->objects.size() == 1 &&
                              regions->objects.size() == 1 &&
                              cropped->objects[0]->provenance == box->id() &&
                              regions->objects[0]->provenance == box->id() &&
                              cropped->objects[0]->roi &&
                              cropped->objects[0]->roi->label == "roi0" &&
                              cropped->objects[0]->id == "cloud.roi0",
                          "prov: box outputs provenance + roi0 label");

        Graph g3;
        auto* load3 = g3.addNode("load_cloud");
        g3.setParam(load3->id(), "path", ParamValue{path});
        auto* pd = g3.addNode("plane_detect");
        g3.setParam(pd->id(), "distance_threshold", ParamValue{1.0});
        g3.setParam(pd->id(), "min_inliers", ParamValue{50});
        g3.setParam(pd->id(), "iterations", ParamValue{100});
        g3.connect(load3->id(), 0, pd->id(), 0);
        failures += check(g3.execute(), "prov: plane execute ok");
        const auto* planes = g3.output(pd->id());
        failures += check(planes && !planes->objects.empty() &&
                              planes->objects[0]->provenance == pd->id() &&
                              planes->objects[0]->regions[0].provenance == pd->id(),
                          "prov: plane object+region provenance = node id");
    }

    // ---- roi_crop index alignment (zip + broadcast) ----
    {
        const std::filesystem::path src_dir = dir / "cropalign_src";
        std::filesystem::create_directories(src_dir);
        writeTemp(src_dir, "f0.ply", makeLine(100, 0.0f));
        writeTemp(src_dir, "f1.ply", makeLine(80, 5.0f));

        Graph g;
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "folder", ParamValue{src_dir.string()});
        g.setParam(load->id(), "mode", ParamValue{std::string("all")});
        auto* box = g.addNode("box_roi");
        // One box list with two boxes; region output is 2 objects.
        g.setParam(box->id(), "box_count", ParamValue{2});
        g.setParam(box->id(), "boxes_json",
                   ParamValue{std::string(
                       R"([{"xmin":-10,"xmax":49,"ymin":-10,"ymax":10,"zmin":-10,"zmax":10},)"
                       R"({"xmin":60,"xmax":110,"ymin":-10,"ymax":10,"zmin":-10,"zmax":10}])")});
        auto* crop = g.addNode("roi_crop");
        g.connect(load->id(), 0, box->id(), 0);
        // F x M zip: crop the box_roi cloud output (4) with the box_roi
        // region output (4), one box per cropped frame.
        g.connect(box->id(), 0, crop->id(), 0);
        g.connect(box->id(), 1, crop->id(), 1);
        failures += check(g.execute(), "cropalign: execute ok");
        const auto* out = g.output(crop->id());
        failures += check(out && out->objects.size() == 4,
                          "cropalign: F x M crops (2 frames x 2 boxes)");
        if (out && out->objects.size() == 4) {
            failures += check(out->objects[0]->cloud->size() == 50 &&
                                  out->objects[1]->cloud->size() == 40 &&
                                  out->objects[2]->cloud->size() == 50 &&
                                  out->objects[3]->cloud->size() == 20,
                              "cropalign: per-frame/per-box counts");
        }

        // Broadcast: one region applies to every frame.
        Graph g2;
        auto* load2 = g2.addNode("load_cloud");
        g2.setParam(load2->id(), "folder", ParamValue{src_dir.string()});
        g2.setParam(load2->id(), "mode", ParamValue{std::string("all")});
        auto* box2 = g2.addNode("box_roi");
        g2.setParam(box2->id(), "xmin", ParamValue{-10.0});
        g2.setParam(box2->id(), "xmax", ParamValue{49.0});
        g2.setParam(box2->id(), "ymin", ParamValue{-10.0});
        g2.setParam(box2->id(), "ymax", ParamValue{10.0});
        g2.setParam(box2->id(), "zmin", ParamValue{-10.0});
        g2.setParam(box2->id(), "zmax", ParamValue{10.0});
        auto* crop2 = g2.addNode("roi_crop");
        g2.connect(load2->id(), 0, box2->id(), 0);
        g2.connect(load2->id(), 0, crop2->id(), 0);
        g2.connect(box2->id(), 1, crop2->id(), 1);
        failures += check(g2.execute(), "cropalign: broadcast execute ok");
        const auto* out2 = g2.output(crop2->id());
        failures += check(out2 && out2->objects.size() == 2 &&
                              out2->objects[0]->cloud->size() == 50 &&
                              out2->objects[1]->cloud->size() == 50,
                          "cropalign: one region broadcasts to all frames");

        // Length mismatch (2 clouds vs 3 regions) fails with a clear error.
        Graph g3;
        auto* load3 = g3.addNode("load_cloud");
        g3.setParam(load3->id(), "folder", ParamValue{src_dir.string()});
        g3.setParam(load3->id(), "mode", ParamValue{std::string("all")});
        auto* box3 = g3.addNode("box_roi");
        g3.setParam(box3->id(), "box_count", ParamValue{3});
        g3.setParam(box3->id(), "boxes_json",
                    ParamValue{std::string(
                        R"([{"xmin":-10,"xmax":49,"ymin":-10,"ymax":10,"zmin":-10,"zmax":10},)"
                        R"({"xmin":60,"xmax":110,"ymin":-10,"ymax":10,"zmin":-10,"zmax":10},)"
                        R"({"xmin":0,"xmax":20,"ymin":-10,"ymax":10,"zmin":-10,"zmax":10}])")});
        auto* crop3 = g3.addNode("roi_crop");
        g3.connect(load3->id(), 0, box3->id(), 0);
        g3.connect(load3->id(), 0, crop3->id(), 0);
        g3.connect(box3->id(), 1, crop3->id(), 1);
        failures += check(!g3.execute(), "cropalign: length mismatch must fail");
        failures += check(g3.lastError().find("length mismatch") != std::string::npos,
                          "cropalign: error mentions length mismatch");
    }

    // ---- Save: zero-padded + multi-box naming, cross-mode consistent ----
    {
        const std::filesystem::path src_dir = dir / "savename_src";
        std::filesystem::create_directories(src_dir);
        writeTemp(src_dir, "f0.ply", makeLine(10, 0.0f));
        writeTemp(src_dir, "f1.ply", makeLine(20, 1.0f));
        writeTemp(src_dir, "f2.ply", makeLine(30, 2.0f));

        // mode=all + save -> frame_000.ply frame_001.ply frame_002.ply
        const std::filesystem::path out_all = dir / "savename_all";
        Graph g;
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "folder", ParamValue{src_dir.string()});
        g.setParam(load->id(), "mode", ParamValue{std::string("all")});
        auto* save = g.addNode("save_cloud");
        g.setParam(save->id(), "folder", ParamValue{out_all.string()});
        g.setParam(save->id(), "file_name", ParamValue{std::string("cloud")});
        g.connect(load->id(), 0, save->id(), 0);
        failures += check(g.execute(), "savename: all-mode execute ok");
        bool files_ok = true;
        for (const char* n : {"frame_000.ply", "frame_001.ply", "frame_002.ply"}) {
            files_ok = files_ok && std::filesystem::exists(out_all / n);
        }
        failures += check(files_ok, "savename: zero-padded frame names (all)");
        failures += check(!std::filesystem::exists(out_all / "cloud_0.ply"),
                          "savename: no legacy _0 suffix");

        // stream (K=1) + save -> identical names across modes
        const std::filesystem::path out_stream = dir / "savename_stream";
        Graph g2;
        auto* load2 = g2.addNode("load_cloud");
        g2.setParam(load2->id(), "folder", ParamValue{src_dir.string()});
        g2.setParam(load2->id(), "mode", ParamValue{std::string("stream")});
        auto* save2 = g2.addNode("save_cloud");
        g2.setParam(save2->id(), "folder", ParamValue{out_stream.string()});
        g2.setParam(save2->id(), "file_name", ParamValue{std::string("cloud")});
        g2.connect(load2->id(), 0, save2->id(), 0);
        failures += check(g2.executeChunked(1), "savename: stream execute ok");
        bool stream_ok = true;
        for (const char* n : {"frame_000.ply", "frame_001.ply", "frame_002.ply"}) {
            stream_ok = stream_ok && std::filesystem::exists(out_stream / n);
        }
        failures += check(stream_ok, "savename: zero-padded frame names (stream)");

        // multi-box: frame_000.roi0.ply frame_000.roi1.ply ...
        const std::filesystem::path out_box = dir / "savename_box";
        Graph g3;
        auto* load3 = g3.addNode("load_cloud");
        g3.setParam(load3->id(), "folder", ParamValue{src_dir.string()});
        g3.setParam(load3->id(), "mode", ParamValue{std::string("all")});
        auto* box = g3.addNode("box_roi");
        g3.setParam(box->id(), "box_count", ParamValue{2});
        g3.setParam(box->id(), "boxes_json",
                    ParamValue{std::string(
                        R"([{"xmin":-10,"xmax":15,"ymin":-10,"ymax":10,"zmin":-10,"zmax":10},)"
                        R"({"xmin":15,"xmax":40,"ymin":-10,"ymax":10,"zmin":-10,"zmax":10}])")});
        auto* save3 = g3.addNode("save_cloud");
        g3.setParam(save3->id(), "folder", ParamValue{out_box.string()});
        g3.setParam(save3->id(), "file_name", ParamValue{std::string("cloud")});
        g3.connect(load3->id(), 0, box->id(), 0);
        g3.connect(box->id(), 0, save3->id(), 0);
        failures += check(g3.execute(), "savename: multi-box execute ok");
        bool box_ok = true;
        for (const char* n : {"frame_000.roi0.ply", "frame_000.roi1.ply",
                              "frame_001.roi0.ply", "frame_001.roi1.ply",
                              "frame_002.roi0.ply", "frame_002.roi1.ply"}) {
            box_ok = box_ok && std::filesystem::exists(out_box / n);
        }
        failures += check(box_ok, "savename: multi-box roi label names");

        // 1:N outputs without frame ids get zero-padded global indices.
        const std::filesystem::path out_1n = dir / "savename_1n";
        Graph g4;
        auto* load4 = g4.addNode("load_cloud");
        g4.setParam(load4->id(), "path",
                    ParamValue{writeTemp(dir, "savename_blobs.ply", makeBlobs())});
        auto* db = g4.addNode("dbscan");
        g4.setParam(db->id(), "eps", ParamValue{10.0});
        g4.setParam(db->id(), "min_points", ParamValue{20});
        auto* save4 = g4.addNode("save_cloud");
        g4.setParam(save4->id(), "folder", ParamValue{out_1n.string()});
        g4.setParam(save4->id(), "file_name", ParamValue{std::string("cluster")});
        g4.connect(load4->id(), 0, db->id(), 0);
        g4.connect(db->id(), 0, save4->id(), 0);
        failures += check(g4.execute(), "savename: 1:N execute ok");
        const auto* db_out = g4.output(db->id());
        if (db_out) {
            bool idx_ok = true;
            for (std::size_t i = 0; i < db_out->objects.size(); ++i) {
                std::string pad = i < 10 ? "00" : (i < 100 ? "0" : "");
                idx_ok = idx_ok &&
                         std::filesystem::exists(out_1n /
                                                 ("cluster_" + pad + std::to_string(i) +
                                                  ".ply"));
            }
            failures += check(idx_ok, "savename: 1:N indexed names");
        }
    }

    // ---- Solution JSON round-trip ----
    {
        Graph g;
        std::string path;
        path = writeTemp(dir, "点 云 grid.ply", makeGridWithInvalid());
        auto* load = g.addNode("load_cloud");
        g.setParam(load->id(), "path", ParamValue{path});
        auto* clean = g.addNode("remove_invalid");
        auto* vox = g.addNode("voxel_downsample");
        g.setParam(vox->id(), "leaf_size", ParamValue{10.0});
        g.connect(load->id(), 0, clean->id(), 0);
        g.connect(clean->id(), 0, vox->id(), 0);
        const bool solution_exec_ok = g.execute();
        if (!solution_exec_ok) {
            std::cerr << "solution: lastError=" << g.lastError() << "\n";
        }
        failures += check(solution_exec_ok, "solution: execute source ok");
        const auto* src_out = g.output(vox->id());
        const std::int64_t src_count =
            src_out && !src_out->objects.empty() ? src_out->objects[0]->cloud->size() : -1;

        const std::string json_text = pcsearch::pipeline::saveGraphJson(g);
        failures += check(json_text.find("点") != std::string::npos,
                          "solution: non-ascii path survives serialization");

        Graph g2;
        failures += check(pcsearch::pipeline::loadGraphJson(g2, json_text),
                          "solution: load ok");
        failures += check(g2.nodes().size() == 3, "solution: node count");
        failures += check(g2.edges().size() == 2, "solution: edge count");
        auto* vox2 = g2.node(vox->id());
        failures += check(vox2 && vox2->params().getDouble("leaf_size") == 10.0,
                          "solution: param restored");
        auto* load2 = g2.node(load->id());
        failures += check(load2 && load2->params().getString("path") == path,
                          "solution: path restored");
        const bool solution_exec2_ok = g2.execute();
        if (!solution_exec2_ok) {
            std::cerr << "solution: reloaded lastError=" << g2.lastError() << "\n";
        }
        failures += check(solution_exec2_ok, "solution: loaded graph executes");
        const auto* out2 = g2.output(vox->id());
        failures += check(out2 && !out2->objects.empty() &&
                              out2->objects[0]->cloud->size() == src_count,
                          "solution: same output after reload");
    }

    // ---- JSON parser edge cases ----
    {
        using pcsearch::pipeline::json::JsonError;
        using pcsearch::pipeline::json::Value;
        const std::string text =
            R"({"a":1.5,"b":-3,"c":true,"d":null,"e":"x\"y\\z\n\u4e2d","f":[1,2,3],"g":{"h":false}})";
        const Value v = Value::parse(text);
        failures += check(v["a"].asNumber() == 1.5, "json: number");
        failures += check(v["b"].asNumber() == -3.0, "json: negative number");
        failures += check(v["c"].asBool(), "json: true");
        failures += check(v["d"].isNull(), "json: null");
        failures += check(v["e"].asString() == "x\"y\\z\n\xE4\xB8\xAD", "json: escapes");
        failures += check(v["f"].asArray().size() == 3 &&
                              v["f"].asArray()[2].asNumber() == 3.0,
                          "json: array");
        failures += check(!v["g"]["h"].asBool(), "json: nested object");
        failures += check(Value::parse(v.dump()).dump() == v.dump(),
                          "json: dump/parse round-trip");
        bool threw = false;
        try {
            Value::parse(R"({"a":})");
        } catch (const JsonError&) {
            threw = true;
        }
        failures += check(threw, "json: malformed input throws");
    }

    // ---- Params reject NaN/Inf ----
    {
        Graph g;
        auto* box = g.addNode("box_roi");
        bool threw = false;
        try {
            g.setParam(box->id(), "xmin", ParamValue{std::nan("")});
        } catch (const pcsearch::pipeline::ParamsError&) {
            threw = true;
        }
        failures += check(threw, "params: NaN rejected");
        threw = false;
        try {
            g.setParam(box->id(), "xmax",
                       ParamValue{std::numeric_limits<double>::infinity()});
        } catch (const pcsearch::pipeline::ParamsError&) {
            threw = true;
        }
        failures += check(threw, "params: Inf rejected");
        failures += check(box->params().getDouble("xmin") == -100000.0 &&
                              box->params().getDouble("xmax") == 100000.0,
                          "params: values untouched after rejected NaN/Inf");
    }

    // ---- Port kind enforcement ----
    {
        pcsearch::pipeline::NodeRegistry::instance().registerNode(
            "test_region_sink", "Region Sink", "Test",
            [] { return std::make_unique<RegionSinkNode>(std::string{}); });
        pcsearch::pipeline::NodeRegistry::instance().registerNode(
            "test_any_passthrough", "Any Passthrough", "Test",
            [] { return std::make_unique<AnyPassthroughNode>(std::string{}); });
        Graph g;
        auto* load = g.addNode("load_cloud");
        auto* sink = g.addNode("test_region_sink");
        failures += check(!g.canConnect(load->id(), 0, sink->id(), 0),
                          "kind: cloud -> region rejected");
        failures +=
            check(g.connectError().find("type mismatch") != std::string::npos,
                  "kind: connectError mentions type mismatch");
        failures += check(!g.connect(load->id(), 0, sink->id(), 0),
                          "kind: connect() also rejected");
        failures += check(g.edges().empty(), "kind: no edge recorded");

        // Any-kind ports connect to typed ports in either direction.
        auto* any_source = g.addNode("test_any_passthrough");
        auto* any_sink = g.addNode("test_any_passthrough");
        failures += check(g.canConnect(any_source->id(), 0, sink->id(), 0),
                          "kind: any -> region allowed");
        failures += check(g.canConnect(load->id(), 0, any_sink->id(), 0),
                          "kind: cloud -> any allowed");

        // Display 3D input is "any" (PROJECT §8.7): cloud, region and any
        // outputs all connect so several display3d nodes can stack layers.
        auto* disp = g.addNode("display3d");
        failures += check(disp && disp->inputKind(0) == "any",
                          "kind: display3d input kind any");
        failures += check(g.canConnect(load->id(), 0, disp->id(), 0),
                          "kind: cloud -> display3d allowed");
        auto* box = g.addNode("box_roi");
        failures += check(g.canConnect(box->id(), 1, disp->id(), 0),
                          "kind: region -> display3d allowed");
        failures += check(g.canConnect(any_source->id(), 0, disp->id(), 0),
                          "kind: any -> display3d allowed");
    }

    std::filesystem::remove_all(dir);
    if (failures == 0) {
        std::cout << "PASS\n";
        return 0;
    }
    std::cerr << failures << " checks failed\n";
    return 1;
}
