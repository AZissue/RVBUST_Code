// RvcVisionStudio 入口。
// 默认启动 GUI。无头模式：
//   --selftest <ply>  加载 PLY 跑一遍 LoadPLY → Display3D（回调计数断言）
//   --smoke <ply>     测量流水线：LoadPLY → ROI → 降采样 → 平面拟合 → 点面距，
//                     输出数值并断言合理性
// GUI 辅助：--demo <ply>（画布自动构建演示链路）、--autoquit N（N 秒后退出）。
// 退出码 0 = 通过，1 = 失败。

#include <cstdlib>
#include <cstring>
#include <iostream>

#include <QApplication>
#include <QSurfaceFormat>
#include <QTimer>
#include <QVTKOpenGLNativeWidget.h>

#include "core/Engine.h"
#include "core/Process.h"
#include "modules/Modules.h"
#include "modules/acquisition/LoadPlyModule.h"
#include "modules/display/Display3DModule.h"
#include "modules/fit/FitPlaneModule.h"
#include "modules/measure/PointToPlaneDistanceModule.h"
#include "modules/preprocess/BoxRoiModule.h"
#include "modules/preprocess/VoxelDownsampleModule.h"
#include "ui/MainWindow.h"
#include "ui/Theme.h"

namespace {

void printRecords(const rvc::RunResult& result)
{
    for (const auto& rec : result.records) {
        std::cout << "  module '" << rec.name << "' " << (rec.success ? "OK" : "FAILED")
                  << " (" << rec.elapsedMs << " ms)\n";
        for (const auto& log : rec.logs)
            std::cout << "    | " << log << "\n";
    }
    if (!result.error.empty())
        std::cerr << "  process error: " << result.error << "\n";
}

// 无头自测：加载指定 PLY 跑一遍 core::Process
int runSelfTest(const std::string& plyPath)
{
    using namespace rvc;

    Process process;

    const int loadId = process.addNode(LoadPlyModule::kTypeId);
    const int displayId = process.addNode(Display3DModule::kTypeId);
    if (loadId < 0 || displayId < 0) {
        std::cerr << "[selftest] failed to create modules\n";
        return 1;
    }

    process.module(loadId)->setParam("filePath", plyPath);

    std::string err;
    if (!process.addLink(loadId, "cloud", displayId, "cloud", &err)) {
        std::cerr << "[selftest] failed to link modules: " << err << "\n";
        return 1;
    }

    // 显示回调替换为计数断言（无 UI）
    int callbackCount = 0;
    size_t displayedPoints = 0;
    Display3DModule::setDisplayCallback([&](const std::string&, PointCloud cloud, DisplayOverlays) {
        ++callbackCount;
        displayedPoints = cloud ? cloud->size() : 0;
    });

    const RunResult result = Engine::runOnce(process);
    printRecords(result);

    const bool pass = result.ok && result.records.size() == 2 &&
                      result.records[0].success && result.records[1].success &&
                      callbackCount == 1 && displayedPoints > 0;

    std::cout << "[selftest] displayed points: " << displayedPoints
              << ", callbacks: " << callbackCount << "\n";
    std::cout << "[selftest] " << (pass ? "PASS" : "FAIL") << "\n";
    return pass ? 0 : 1;
}

// 无头冒烟：真实 PLY → ROI → 降采样 → 平面拟合 → 点面距
int runSmoke(const std::string& plyPath)
{
    using namespace rvc;

    Process process;
    const int loadId = process.addNode(LoadPlyModule::kTypeId);
    const int roiId = process.addNode(BoxRoiModule::kTypeId);
    const int voxelId = process.addNode(VoxelDownsampleModule::kTypeId);
    const int fitId = process.addNode(FitPlaneModule::kTypeId);
    const int distId = process.addNode(PointToPlaneDistanceModule::kTypeId);
    if (loadId < 0 || roiId < 0 || voxelId < 0 || fitId < 0 || distId < 0) {
        std::cerr << "[smoke] failed to create modules\n";
        return 1;
    }

    process.module(loadId)->setParam("filePath", plyPath);
    // ROI 默认 ±1e9（不裁），仅验证链路可用；降采样 2mm，拟合阈值 5mm

    std::string err;
    const bool linked =
        process.addLink(loadId, "cloud", roiId, "cloud", &err) &&
        process.addLink(roiId, "cloud", voxelId, "cloud", &err) &&
        process.addLink(voxelId, "cloud", fitId, "cloud", &err) &&
        process.addLink(roiId, "roi", fitId, "roi", &err) &&
        process.addLink(fitId, "inliers", distId, "cloud", &err) &&
        process.addLink(fitId, "plane", distId, "plane", &err) &&
        process.addLink(roiId, "roi", distId, "roi", &err);
    if (!linked) {
        std::cerr << "[smoke] failed to link pipeline: " << err << "\n";
        return 1;
    }

    const RunResult result = Engine::runOnce(process);
    printRecords(result);

    // 数值合理性断言
    bool pass = result.ok;
    for (const auto& rec : result.records)
        pass = pass && rec.success;

    double mean = -1.0, maxDist = -1.0;
    if (const double* d = process.cachedOutput(distId, "mean").get<double>())
        mean = *d;
    if (const double* d = process.cachedOutput(distId, "max").get<double>())
        maxDist = *d;

    std::cout << "[smoke] point-to-plane: mean " << mean << " m, max " << maxDist << " m\n";
    // 内点应大部分落在阈值（5mm）内：均值必须显著小于阈值
    pass = pass && mean >= 0.0 && mean < 0.005 && maxDist > 0.0;

    std::cout << "[smoke] " << (pass ? "PASS" : "FAIL") << "\n";
    return pass ? 0 : 1;
}

} // namespace

int main(int argc, char* argv[])
{
    rvc::registerBuiltinModules();

    std::string selfTestPly;
    std::string smokePly;
    std::string demoPly;
    int autoQuitSeconds = 0;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--selftest") == 0 && i + 1 < argc)
            selfTestPly = argv[++i];
        else if (std::strcmp(argv[i], "--smoke") == 0 && i + 1 < argc)
            smokePly = argv[++i];
        else if (std::strcmp(argv[i], "--demo") == 0 && i + 1 < argc)
            demoPly = argv[++i];
        else if (std::strcmp(argv[i], "--autoquit") == 0 && i + 1 < argc)
            autoQuitSeconds = std::atoi(argv[++i]);
    }

    if (!selfTestPly.empty())
        return runSelfTest(selfTestPly);
    if (!smokePly.empty())
        return runSmoke(smokePly);

    // QVTKOpenGLNativeWidget 要求的默认 OpenGL 上下文格式（必须在 QApplication 之前）
    QSurfaceFormat::setDefaultFormat(QVTKOpenGLNativeWidget::defaultFormat());

    QApplication app(argc, argv);
    // 应用 Foundation 设计系统主题（字体/QPalette/全局 QSS/QtNodes 风格）
    rvc::Theme::apply(app);
    rvc::MainWindow window;
    window.show();

    // GUI 演示链路：窗口显示后构建 LoadPLY → Display3D 并运行一次
    if (!demoPly.empty())
        QTimer::singleShot(500, &window, [&window, demoPly] {
            window.loadDemoFlow(QString::fromStdString(demoPly));
        });

    // 供自动化验证：N 秒后自动退出
    if (autoQuitSeconds > 0)
        QTimer::singleShot(autoQuitSeconds * 1000, &app, &QApplication::quit);

    return QApplication::exec();
}
