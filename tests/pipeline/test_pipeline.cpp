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
        failures += check(g.execute(), "solution: execute source ok");
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
        failures += check(g2.execute(), "solution: loaded graph executes");
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
    }

    std::filesystem::remove_all(dir);
    if (failures == 0) {
        std::cout << "PASS\n";
        return 0;
    }
    std::cerr << failures << " checks failed\n";
    return 1;
}
