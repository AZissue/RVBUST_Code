// core / modules 单元测试（Catch2 v3）
//  core：拓扑排序、环拒绝、JSON 往返、真实 PLY 加载
//  modules（M2）：合成点云数值断言（噪声 sigma=1e-4 m，远小于拟合阈值）

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>

#include <random>

#include <QDir>
#include <QFile>

#include "core/Engine.h"
#include "core/ModuleRegistry.h"
#include "core/Process.h"
#include "core/Solution.h"
#include "modules/Modules.h"
#include "modules/acquisition/LoadPlyModule.h"
#include "modules/display/Display3DModule.h"
#include "modules/fit/FitCircleModule.h"
#include "modules/fit/FitLineModule.h"
#include "modules/fit/FitPlaneModule.h"
#include "modules/measure/BoundingBoxMeasureModule.h"
#include "modules/measure/PlaneToPlaneModule.h"
#include "modules/measure/PointToPlaneDistanceModule.h"
#include "modules/preprocess/BoxRoiModule.h"

using namespace rvc;

namespace {

// ---- dummy 测试模块：Source → Middle → Sink，execute 时记录执行顺序 ----

std::vector<std::string>* g_execOrder = nullptr;

class SourceModule : public ModuleBase {
public:
    SourceModule() { displayName_ = "Source"; }
    std::string typeId() const override { return "Test.Source"; }
    std::vector<PortDecl> inputPorts() const override { return {}; }
    std::vector<PortDecl> outputPorts() const override { return {{"out", DataType::Scalar}}; }
    bool execute(ModuleContext& ctx) override
    {
        g_execOrder->push_back("Source");
        ctx.setOutput("out", makePortValue(DataType::Scalar, 42.0));
        return true;
    }
};

class MiddleModule : public ModuleBase {
public:
    MiddleModule() { displayName_ = "Middle"; }
    std::string typeId() const override { return "Test.Middle"; }
    std::vector<PortDecl> inputPorts() const override { return {{"in", DataType::Scalar}}; }
    std::vector<PortDecl> outputPorts() const override { return {{"out", DataType::Scalar}}; }
    bool execute(ModuleContext& ctx) override
    {
        if (!ctx.hasInput("in")) {
            ctx.log("missing input");
            return false;
        }
        g_execOrder->push_back("Middle");
        ctx.setOutput("out", ctx.input("in"));
        return true;
    }
};

class SinkModule : public ModuleBase {
public:
    SinkModule() { displayName_ = "Sink"; }
    std::string typeId() const override { return "Test.Sink"; }
    std::vector<PortDecl> inputPorts() const override { return {{"in", DataType::Scalar}}; }
    std::vector<PortDecl> outputPorts() const override { return {}; }
    bool execute(ModuleContext& ctx) override
    {
        if (!ctx.hasInput("in")) {
            ctx.log("missing input");
            return false;
        }
        g_execOrder->push_back("Sink");
        return true;
    }
};

void registerTestModules()
{
    static bool done = false;
    if (done)
        return;
    done = true;
    auto& reg = ModuleRegistry::instance();
    reg.reg<SourceModule>("Test.Source", "测试", "Source");
    reg.reg<MiddleModule>("Test.Middle", "测试", "Middle");
    reg.reg<SinkModule>("Test.Sink", "测试", "Sink");
}

// ---- 合成点云生成 ----

PointCloud makeGridCloud(int n = 21, double step = 0.01, double z = 0.0)
{
    auto cloud = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < n; ++j) {
            cloud->points.emplace_back(static_cast<float>((i - n / 2) * step),
                                       static_cast<float>((j - n / 2) * step),
                                       static_cast<float>(z));
        }
    }
    cloud->width = static_cast<std::uint32_t>(cloud->size());
    cloud->height = 1;
    cloud->is_dense = true;
    return cloud;
}

PointCloud makeNoisyPlaneCloud(double z, int count, double sigma)
{
    auto cloud = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    std::mt19937 rng(42);
    std::uniform_real_distribution<double> xy(-0.1, 0.1);
    std::normal_distribution<double> noise(0.0, sigma);
    for (int i = 0; i < count; ++i)
        cloud->points.emplace_back(static_cast<float>(xy(rng)), static_cast<float>(xy(rng)),
                                   static_cast<float>(z + noise(rng)));
    cloud->width = static_cast<std::uint32_t>(cloud->size());
    cloud->height = 1;
    cloud->is_dense = true;
    return cloud;
}

PointCloud makeNoisyLineCloud(int count, double sigma)
{
    // 真直线：过原点、方向 (1,0,0)
    auto cloud = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    std::mt19937 rng(7);
    std::uniform_real_distribution<double> t(-0.1, 0.1);
    std::normal_distribution<double> noise(0.0, sigma);
    for (int i = 0; i < count; ++i)
        cloud->points.emplace_back(static_cast<float>(t(rng)), static_cast<float>(noise(rng)),
                                   static_cast<float>(noise(rng)));
    cloud->width = static_cast<std::uint32_t>(cloud->size());
    cloud->height = 1;
    cloud->is_dense = true;
    return cloud;
}

PointCloud makeNoisyCircleCloud(double radius, double z, int count, double sigma)
{
    // 真圆：圆心 (0,0,z)，法线 (0,0,1)，半径 radius
    auto cloud = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    std::mt19937 rng(99);
    std::uniform_real_distribution<double> ang(0.0, 6.28318530718);
    std::normal_distribution<double> noise(0.0, sigma);
    for (int i = 0; i < count; ++i) {
        const double a = ang(rng);
        cloud->points.emplace_back(static_cast<float>(radius * std::cos(a) + noise(rng)),
                                   static_cast<float>(radius * std::sin(a) + noise(rng)),
                                   static_cast<float>(z + noise(rng)));
    }
    cloud->width = static_cast<std::uint32_t>(cloud->size());
    cloud->height = 1;
    cloud->is_dense = true;
    return cloud;
}

// 直接构造上下文执行（无需流程）：拟合/预处理/测量模块共用
struct DirectRun {
    bool ok = false;
    std::vector<std::string> logs;
    std::map<std::string, PortValue> outputs;
};

template <typename ModuleT>
DirectRun runDirect(ModuleT& module, std::map<std::string, PortValue> inputs)
{
    DirectRun r;
    ModuleContext ctx(inputs, r.logs);
    r.ok = module.execute(ctx);
    r.outputs = ctx.outputs();
    return r;
}

// 单模块 + 点云输入的便捷入口（可选参数覆盖 / 可选额外输入端口）
DirectRun runModuleWithCloud(const std::string& typeId, PointCloud cloud,
                             const std::map<std::string, ParamValue>& params = {},
                             const std::map<std::string, PortValue>& extraInputs = {})
{
    registerBuiltinModules();
    ModulePtr m = ModuleRegistry::instance().create(typeId);
    DirectRun r;
    if (!m) {
        r.logs.push_back("unknown module type: " + typeId);
        return r;
    }
    for (const auto& [k, v] : params)
        m->setParam(k, v);
    std::map<std::string, PortValue> inputs;
    inputs["cloud"] = makePortValue(DataType::PointCloud, std::move(cloud));
    for (const auto& [k, v] : extraInputs)
        inputs[k] = v;
    ModuleContext ctx(inputs, r.logs);
    r.ok = m->execute(ctx);
    r.outputs = ctx.outputs();
    return r;
}

} // namespace

// ==================== core 用例 ====================

TEST_CASE("Process: 3-module graph executes in topological order", "[core]")
{
    registerTestModules();

    std::vector<std::string> order;
    g_execOrder = &order;

    Process p;
    const int a = p.addNode("Test.Source");
    const int b = p.addNode("Test.Middle");
    const int c = p.addNode("Test.Sink");
    REQUIRE(a > 0);
    REQUIRE(b > 0);
    REQUIRE(c > 0);

    std::string err;
    // 故意先连下游段，验证排序不依赖建边顺序
    REQUIRE(p.addLink(b, "out", c, "in", &err));
    REQUIRE(p.addLink(a, "out", b, "in", &err));

    const RunResult result = Engine::runOnce(p);
    g_execOrder = nullptr;

    REQUIRE(result.ok);
    REQUIRE(result.error.empty());
    REQUIRE(result.records.size() == 3);
    for (const auto& rec : result.records) {
        REQUIRE(rec.success);
        REQUIRE(rec.elapsedMs >= 0.0);
    }

    REQUIRE(order == std::vector<std::string>{"Source", "Middle", "Sink"});
}

TEST_CASE("Process: cyclic connection is rejected", "[core]")
{
    registerTestModules();

    Process p;
    const int b = p.addNode("Test.Middle");
    const int c = p.addNode("Test.Middle");

    std::string err;
    REQUIRE(p.addLink(b, "out", c, "in", &err));

    // 反向再连即构成环：必须被拒绝并给出原因
    err.clear();
    REQUIRE_FALSE(p.addLink(c, "out", b, "in", &err));
    REQUIRE(err.find("cycle") != std::string::npos);

    // 自连同样拒绝
    REQUIRE_FALSE(p.addLink(b, "out", b, "in", &err));

    // 类型不符禁止连线（PointCloud 输出 → Scalar 输入）
    registerBuiltinModules();
    const int ply = p.addNode(LoadPlyModule::kTypeId);
    err.clear();
    REQUIRE_FALSE(p.addLink(ply, "cloud", b, "in", &err));
    REQUIRE(err.find("mismatch") != std::string::npos);
}

TEST_CASE("Solution: JSON save-load roundtrip is consistent", "[core]")
{
    registerBuiltinModules();

    Solution s;
    const int a = s.process().addNode(LoadPlyModule::kTypeId);
    const int b = s.process().addNode("Display.Display3D");
    REQUIRE(a > 0);
    REQUIRE(b > 0);

    ModuleBase* loadPly = s.process().module(a);
    REQUIRE(loadPly != nullptr);
    REQUIRE(loadPly->setParam("filePath", std::string("D:/data/demo.ply")));
    s.process().setNodePosition(a, 123.0, 456.0);

    std::string err;
    REQUIRE(s.process().addLink(a, "cloud", b, "cloud", &err));

    const QString path = QDir::temp().filePath(QStringLiteral("rvs_roundtrip_test.json"));
    QString qerr;
    REQUIRE(s.save(path, &qerr));

    Solution s2;
    REQUIRE(s2.load(path, &qerr));

    REQUIRE(s2.process().nodes().size() == 2);
    REQUIRE(s2.process().links().size() == 1);

    // 参数与布局往返一致
    ModuleBase* loadPly2 = s2.process().module(a);
    REQUIRE(loadPly2 != nullptr);
    REQUIRE(loadPly2->getString("filePath") == "D:/data/demo.ply");
    const ProcessNode* nodeA = s2.process().node(a);
    REQUIRE(nodeA != nullptr);
    REQUIRE(nodeA->x == Catch::Approx(123.0));
    REQUIRE(nodeA->y == Catch::Approx(456.0));

    const ProcessLink& link = s2.process().links().front();
    REQUIRE(link.fromNode == a);
    REQUIRE(link.fromPort == "cloud");
    REQUIRE(link.toNode == b);
    REQUIRE(link.toPort == "cloud");

    QFile::remove(path);
}

TEST_CASE("LoadPlyModule: real PLY loads with points > 0", "[modules]")
{
    registerBuiltinModules();

    Process p;
    const int a = p.addNode(LoadPlyModule::kTypeId);
    REQUIRE(a > 0);

    ModuleBase* loadPly = p.module(a);
    REQUIRE(loadPly != nullptr);
    REQUIRE(loadPly->setParam("filePath", std::string(RVC_TEST_PLY_PATH)));

    const RunResult result = Engine::runOnce(p);
    REQUIRE(result.ok);
    REQUIRE(result.records.size() == 1);
    REQUIRE(result.records[0].success);

    REQUIRE(p.hasCachedOutput(a, "cloud"));
    const PortValue out = p.cachedOutput(a, "cloud");
    const PointCloud* cloud = out.get<PointCloud>();
    REQUIRE(cloud != nullptr);
    REQUIRE(*cloud != nullptr);
    REQUIRE((*cloud)->size() > 0);
}

// ==================== M2：拟合（合成点云数值断言） ====================

TEST_CASE("FitPlane: recovers z=0.05 plane from noisy synthetic cloud", "[fit]")
{
    // 噪声 sigma=1e-4 m，阈值 2mm；roiEnabled=true 使用默认全范围（拟合/测量强制 ROI）
    const DirectRun r = runModuleWithCloud(FitPlaneModule::kTypeId,
                                           makeNoisyPlaneCloud(0.05, 3000, 1e-4),
                                           {{"distanceThreshold", 0.002}, {"roiEnabled", true}});
    REQUIRE(r.ok);

    const Plane3D* plane = r.outputs.at("plane").get<Plane3D>();
    REQUIRE(plane != nullptr);
    // 法线 ≈ (0,0,±1)（模块内已对齐 +Z），d ≈ -0.05
    REQUIRE(std::fabs(plane->c) == Catch::Approx(1.0).margin(1e-2));
    REQUIRE(std::fabs(plane->a) < 1e-2);
    REQUIRE(std::fabs(plane->b) < 1e-2);
    REQUIRE(static_cast<double>(plane->d) == Catch::Approx(-0.05).margin(1e-2));

    const PointCloud* inliers = r.outputs.at("inliers").get<PointCloud>();
    REQUIRE(inliers != nullptr);
    REQUIRE((*inliers)->size() > 2000);
}

TEST_CASE("FitLine: recovers x-axis line from noisy synthetic cloud", "[fit]")
{
    const DirectRun r = runModuleWithCloud(FitLineModule::kTypeId,
                                           makeNoisyLineCloud(3000, 1e-4),
                                           {{"distanceThreshold", 0.002}, {"roiEnabled", true}});
    REQUIRE(r.ok);

    const Line3D* line = r.outputs.at("line").get<Line3D>();
    REQUIRE(line != nullptr);
    // 方向 ≈ ±(1,0,0)
    REQUIRE(std::fabs(line->direction.x()) == Catch::Approx(1.0).margin(1e-2));
    // 线上点应贴近真直线（y、z ≈ 0）
    REQUIRE(std::fabs(line->point.y()) < 1e-2);
    REQUIRE(std::fabs(line->point.z()) < 1e-2);
}

TEST_CASE("FitCircle: recovers r=0.1 circle from noisy synthetic cloud", "[fit]")
{
    const DirectRun r = runModuleWithCloud(FitCircleModule::kTypeId,
                                           makeNoisyCircleCloud(0.1, 0.02, 4000, 1e-4),
                                           {{"distanceThreshold", 0.002},
                                            {"maxIterations", 50000},
                                            {"radiusMin", 0.05},
                                            {"radiusMax", 0.2},
                                            {"roiEnabled", true}});
    REQUIRE(r.ok);

    const Circle3D* circle = r.outputs.at("circle").get<Circle3D>();
    REQUIRE(circle != nullptr);
    // RANSAC 圆拟合稳定性有限：半径容差 5%，圆心/法线 1.5e-2
    REQUIRE(static_cast<double>(circle->radius) == Catch::Approx(0.1).epsilon(0.05));
    REQUIRE(circle->center.x() == Catch::Approx(0.0).margin(1.5e-2));
    REQUIRE(circle->center.y() == Catch::Approx(0.0).margin(1.5e-2));
    REQUIRE(circle->center.z() == Catch::Approx(0.02).margin(1.5e-2));
    REQUIRE(std::fabs(circle->normal.z()) == Catch::Approx(1.0).margin(2e-2));
}

// ==================== M2：预处理 ====================

TEST_CASE("BoxRoi: keeps exactly the points inside the box", "[preprocess]")
{
    // 21x21 网格 x,y ∈ [-0.1, 0.1]（步长 0.01），ROI ±0.0501 → 每轴 11 个点 → 121
    const DirectRun r = runModuleWithCloud(BoxRoiModule::kTypeId, makeGridCloud(),
                                           {{"xmin", -0.0501},
                                            {"xmax", 0.0501},
                                            {"ymin", -0.0501},
                                            {"ymax", 0.0501}});
    REQUIRE(r.ok);

    const PointCloud* out = r.outputs.at("cloud").get<PointCloud>();
    REQUIRE(out != nullptr);
    REQUIRE((*out)->size() == 121);
}

// ==================== M2：测量 ====================

TEST_CASE("PointToPlaneDistance: grid at z=0.05 over plane z=0", "[measure]")
{
    PointToPlaneDistanceModule module;
    module.setParam("roiEnabled", true);  // 强制 ROI：默认全范围即可

    Plane3D plane{0, 0, 1, 0};  // z = 0
    std::map<std::string, PortValue> inputs;
    inputs["cloud"] = makePortValue(DataType::PointCloud, makeGridCloud(21, 0.01, 0.05));
    inputs["plane"] = makePortValue(DataType::Plane, plane);

    const DirectRun r = runDirect(module, std::move(inputs));
    REQUIRE(r.ok);
    REQUIRE(r.outputs.at("mean").get<double>() != nullptr);
    REQUIRE(*r.outputs.at("mean").get<double>() == Catch::Approx(0.05).margin(1e-6));
    REQUIRE(*r.outputs.at("max").get<double>() == Catch::Approx(0.05).margin(1e-6));
}

TEST_CASE("PlaneToPlane: parallel planes distance and angle", "[measure]")
{
    PlaneToPlaneModule module;

    // 平行面：z=0.05 与 z=0.03（法线相反，验证对齐逻辑）
    Plane3D a{0, 0, 1, -0.05f};
    Plane3D b{0, 0, -1, 0.03f};
    std::map<std::string, PortValue> inputs;
    inputs["planeA"] = makePortValue(DataType::Plane, a);
    inputs["planeB"] = makePortValue(DataType::Plane, b);

    const DirectRun r = runDirect(module, std::move(inputs));
    REQUIRE(r.ok);
    REQUIRE(*r.outputs.at("angle").get<double>() == Catch::Approx(0.0).margin(1e-6));
    REQUIRE(*r.outputs.at("distance").get<double>() == Catch::Approx(0.02).margin(1e-6));
}

TEST_CASE("PlaneToPlane: perpendicular planes give no distance output", "[measure]")
{
    PlaneToPlaneModule module;

    Plane3D a{0, 0, 1, 0};
    Plane3D b{1, 0, 0, 0};
    std::map<std::string, PortValue> inputs;
    inputs["planeA"] = makePortValue(DataType::Plane, a);
    inputs["planeB"] = makePortValue(DataType::Plane, b);

    const DirectRun r = runDirect(module, std::move(inputs));
    REQUIRE(r.ok);
    REQUIRE(*r.outputs.at("angle").get<double>() == Catch::Approx(90.0).margin(1e-6));
    // 不平行：distance 端口不给值
    REQUIRE(r.outputs.count("distance") == 0);
}

TEST_CASE("BoundingBox: matches synthetic grid extents", "[measure]")
{
    BoundingBoxMeasureModule module;
    module.setParam("roiEnabled", true);  // 强制 ROI：默认全范围即可

    std::map<std::string, PortValue> inputs;
    inputs["cloud"] = makePortValue(DataType::PointCloud, makeGridCloud(21, 0.01, 0.07));

    const DirectRun r = runDirect(module, std::move(inputs));
    REQUIRE(r.ok);
    REQUIRE(*r.outputs.at("sizeX").get<double>() == Catch::Approx(0.2).margin(1e-6));
    REQUIRE(*r.outputs.at("sizeY").get<double>() == Catch::Approx(0.2).margin(1e-6));
    REQUIRE(*r.outputs.at("sizeZ").get<double>() == Catch::Approx(0.0).margin(1e-6));
}

// ==================== M2：可选端口 / 参数机制 ====================

TEST_CASE("Display3D: runs with optional ports unconnected", "[modules]")
{
    Display3DModule module;

    int callbackCount = 0;
    Display3DModule::setDisplayCallback(
        [&callbackCount](const std::string&, PointCloud, DisplayOverlays overlays) {
            ++callbackCount;
            // 可选端口未连接 → 叠加层全部为空
            REQUIRE_FALSE(overlays.plane.has_value());
            REQUIRE_FALSE(overlays.line.has_value());
            REQUIRE_FALSE(overlays.circle.has_value());
        });

    std::map<std::string, PortValue> inputs;
    inputs["cloud"] = makePortValue(DataType::PointCloud, makeGridCloud());
    const DirectRun r = runDirect(module, std::move(inputs));

    REQUIRE(r.ok);
    REQUIRE(callbackCount == 1);
    Display3DModule::setDisplayCallback(nullptr);
}

TEST_CASE("Params: generic mechanism validates names and types", "[core]")
{
    BoxRoiModule module;
    REQUIRE(module.paramDescs().size() == 6);

    REQUIRE(module.setParam("xmin", -0.1));
    REQUIRE(module.getDouble("xmin") == Catch::Approx(-0.1));
    // 不存在的参数 / 类型不符
    REQUIRE_FALSE(module.setParam("no_such_param", 1.0));
    REQUIRE_FALSE(module.setParam("xmin", std::string("oops")));
}

// 默认值检查
TEST_CASE("Params: defaults are applied", "[core]")
{
    registerBuiltinModules();
    ModulePtr m = ModuleRegistry::instance().create("Preprocess.VoxelDownsample");
    REQUIRE(m != nullptr);
    REQUIRE(m->getDouble("leafSize") == Catch::Approx(0.002));
}

TEST_CASE("Solution: JSON roundtrip preserves new param mechanism values", "[core]")
{
    registerBuiltinModules();

    Solution s;
    const int a = s.process().addNode(BoxRoiModule::kTypeId);
    REQUIRE(a > 0);
    ModuleBase* roi = s.process().module(a);
    REQUIRE(roi->setParam("xmin", -0.1));
    REQUIRE(roi->setParam("zmax", 0.3));

    const QString path = QDir::temp().filePath(QStringLiteral("rvs_param_roundtrip_test.json"));
    QString qerr;
    REQUIRE(s.save(path, &qerr));

    Solution s2;
    REQUIRE(s2.load(path, &qerr));
    ModuleBase* roi2 = s2.process().module(a);
    REQUIRE(roi2 != nullptr);
    REQUIRE(roi2->getDouble("xmin") == Catch::Approx(-0.1));
    REQUIRE(roi2->getDouble("zmax") == Catch::Approx(0.3));
    // 未显式设置的参数保持默认值
    REQUIRE(roi2->getDouble("ymin") == Catch::Approx(-1e9));

    QFile::remove(path);
}

// ==================== M3：ROI 数据类型与联动裁剪 ====================

namespace {

// 主平面 A（z=0.05，x∈[-0.1,0.1]，1500 点）+ 远处干扰平面 B（z=0.5，x∈[0.4,0.6]，4000 点）
PointCloud makeTwoPlaneCloud()
{
    auto cloud = std::make_shared<pcl::PointCloud<pcl::PointXYZ>>();
    std::mt19937 rng(2024);
    std::normal_distribution<double> noise(0.0, 1e-4);
    std::uniform_real_distribution<double> xa(-0.1, 0.1), ya(-0.1, 0.1);
    for (int i = 0; i < 1500; ++i)
        cloud->points.emplace_back(static_cast<float>(xa(rng)), static_cast<float>(ya(rng)),
                                   static_cast<float>(0.05 + noise(rng)));
    std::uniform_real_distribution<double> xb(0.4, 0.6), yb(-0.1, 0.1);
    for (int i = 0; i < 4000; ++i)
        cloud->points.emplace_back(static_cast<float>(xb(rng)), static_cast<float>(yb(rng)),
                                   static_cast<float>(0.5 + noise(rng)));
    cloud->width = static_cast<std::uint32_t>(cloud->size());
    cloud->height = 1;
    cloud->is_dense = true;
    return cloud;
}

} // namespace

TEST_CASE("BoxRoi: exports roi output port matching params", "[roi]")
{
    const DirectRun r = runModuleWithCloud(BoxRoiModule::kTypeId, makeGridCloud(),
                                           {{"xmin", -0.0501},
                                            {"xmax", 0.0501},
                                            {"ymin", -0.0501},
                                            {"ymax", 0.0501},
                                            {"zmin", -1.0},
                                            {"zmax", 1.0}});
    REQUIRE(r.ok);

    const RoiBox* roi = r.outputs.at("roi").get<RoiBox>();
    REQUIRE(roi != nullptr);
    REQUIRE(roi->valid);
    REQUIRE(roi->min.x() == Catch::Approx(-0.0501).margin(1e-6));
    REQUIRE(roi->max.x() == Catch::Approx(0.0501).margin(1e-6));
    REQUIRE(roi->min.z() == Catch::Approx(-1.0).margin(1e-6));
    REQUIRE(roi->max.z() == Catch::Approx(1.0).margin(1e-6));
}

TEST_CASE("FitPlane: without roi the module fails", "[roi]")
{
    // 拟合/测量模块强制要求 ROI：未连线且未启用自有参数时应失败
    const DirectRun r = runModuleWithCloud(FitPlaneModule::kTypeId, makeTwoPlaneCloud(),
                                           {{"distanceThreshold", 0.002}});
    REQUIRE_FALSE(r.ok);
    bool foundRoiError = false;
    for (const auto& log : r.logs) {
        if (log.find("ROI not set") != std::string::npos)
            foundRoiError = true;
    }
    REQUIRE(foundRoiError);
}

TEST_CASE("FitPlane: linked roi crops out the distractor plane", "[roi]")
{
    // 连线 roi 只保留主平面区域 → 拟合 z=0.05
    const RoiBox roi = RoiBox::fromMinMax({-0.2f, -0.2f, -1.0f}, {0.2f, 0.2f, 1.0f});
    const DirectRun r = runModuleWithCloud(FitPlaneModule::kTypeId, makeTwoPlaneCloud(),
                                           {{"distanceThreshold", 0.002}},
                                           {{"roi", makePortValue(DataType::Roi, roi)}});
    REQUIRE(r.ok);
    const Plane3D* plane = r.outputs.at("plane").get<Plane3D>();
    REQUIRE(plane != nullptr);
    REQUIRE(static_cast<double>(plane->d) == Catch::Approx(-0.05).margin(1e-2));
}

TEST_CASE("FitPlane: own roi params path works the same", "[roi]")
{
    // 自有 ROI 参数（roiEnabled=true）与连线路径等价
    const DirectRun r = runModuleWithCloud(FitPlaneModule::kTypeId, makeTwoPlaneCloud(),
                                           {{"distanceThreshold", 0.002},
                                            {"roiEnabled", true},
                                            {"roiXmin", -0.2},
                                            {"roiXmax", 0.2},
                                            {"roiYmin", -0.2},
                                            {"roiYmax", 0.2},
                                            {"roiZmin", -1.0},
                                            {"roiZmax", 1.0}});
    REQUIRE(r.ok);
    const Plane3D* plane = r.outputs.at("plane").get<Plane3D>();
    REQUIRE(plane != nullptr);
    REQUIRE(static_cast<double>(plane->d) == Catch::Approx(-0.05).margin(1e-2));
}

TEST_CASE("FitPlane: linked roi wins over own roi params", "[roi]")
{
    // 优先级：连线 roi > 自有参数。自有参数故意指向干扰面，连线指向主平面。
    const RoiBox roi = RoiBox::fromMinMax({-0.2f, -0.2f, -1.0f}, {0.2f, 0.2f, 1.0f});
    const DirectRun r = runModuleWithCloud(FitPlaneModule::kTypeId, makeTwoPlaneCloud(),
                                           {{"distanceThreshold", 0.002},
                                            {"roiEnabled", true},
                                            {"roiXmin", 0.3},
                                            {"roiXmax", 0.7}},
                                           {{"roi", makePortValue(DataType::Roi, roi)}});
    REQUIRE(r.ok);
    const Plane3D* plane = r.outputs.at("plane").get<Plane3D>();
    REQUIRE(plane != nullptr);
    REQUIRE(static_cast<double>(plane->d) == Catch::Approx(-0.05).margin(1e-2));
}

TEST_CASE("BoundingBox: respects linked roi", "[roi]")
{
    // 网格 0.2x0.2，roi 只留 |x|<=0.05 → sizeX ≈ 0.1
    const RoiBox roi = RoiBox::fromMinMax({-0.05f, -1.0f, -1.0f}, {0.05f, 1.0f, 1.0f});
    BoundingBoxMeasureModule module;
    std::map<std::string, PortValue> inputs;
    inputs["cloud"] = makePortValue(DataType::PointCloud, makeGridCloud(21, 0.01, 0.0));
    inputs["roi"] = makePortValue(DataType::Roi, roi);

    const DirectRun r = runDirect(module, std::move(inputs));
    REQUIRE(r.ok);
    REQUIRE(*r.outputs.at("sizeX").get<double>() == Catch::Approx(0.1).margin(1e-6));
    REQUIRE(*r.outputs.at("sizeY").get<double>() == Catch::Approx(0.2).margin(1e-6));
}

TEST_CASE("RoiBox: 2D mode ignores z axis", "[roi]")
{
    const RoiBox roi2d = RoiBox::fromMinMax({-0.1f, -0.1f, -1e9f}, {0.1f, 0.1f, 1e9f}, true);
    REQUIRE(roi2d.is2D);
    REQUIRE(roi2d.contains(0.05f, 0.05f, 999.0f));
    REQUIRE(roi2d.contains(0.05f, 0.05f, -999.0f));
    REQUIRE_FALSE(roi2d.contains(0.15f, 0.05f, 0.0f));

    const RoiBox roi3d = RoiBox::fromMinMax({-0.1f, -0.1f, -0.1f}, {0.1f, 0.1f, 0.1f}, false);
    REQUIRE_FALSE(roi3d.is2D);
    REQUIRE(roi3d.contains(0.05f, 0.05f, 0.05f));
    REQUIRE_FALSE(roi3d.contains(0.05f, 0.05f, 0.15f));
}

TEST_CASE("RoiBox: write/read params roundtrip preserves 2D flag", "[roi]")
{
    FitPlaneModule module;  // declareRoiParams 声明了 roiXxx 参数组
    const RoiBox roi2d = RoiBox::fromMinMax({-0.2f, -0.3f, -1e9f}, {0.2f, 0.3f, 1e9f}, true);
    REQUIRE(writeRoiToParams(module, roi2d));

    const RoiBox readBack = readRoiFromParams(module);
    REQUIRE(readBack.valid);
    REQUIRE(readBack.is2D);
    REQUIRE(readBack.min.x() == Catch::Approx(-0.2f));
    REQUIRE(readBack.max.x() == Catch::Approx(0.2f));
    REQUIRE(readBack.min.y() == Catch::Approx(-0.3f));
    REQUIRE(readBack.max.y() == Catch::Approx(0.3f));
    REQUIRE(readBack.min.z() == Catch::Approx(-1e9f));
    REQUIRE(readBack.max.z() == Catch::Approx(1e9f));
}
