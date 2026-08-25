#include "main_window.h"
#include "simple_translator.h"
#include "themes.h"

#include "pcsearch/pipeline/graph.h"
#include "pcsearch/pipeline/nodes/core_nodes.h"

#include <QApplication>
#include <QCommandLineParser>
#include <QSurfaceFormat>
#include <QTimer>

#ifdef PCSEARCH_HAS_VTK
#include <QVTKOpenGLNativeWidget.h>
#endif

#include <cstdio>
#include <cstdint>

namespace {

// Headless regression entry used by CI / smoke scripts:
// load -> remove invalid -> voxel downsample, then report point count.
int runSmoke(const QString& plyPath) {
    using namespace pcsearch::pipeline;
    registerCoreNodes();
    Graph g;
    auto* load = g.addNode("load_cloud");
    g.setParam(load->id(), "path", ParamValue{plyPath.toStdString()});
    g.setParam(load->id(), "source_unit", ParamValue{std::string("millimeter")});
    auto* clean = g.addNode("remove_invalid");
    auto* vox = g.addNode("voxel_downsample");
    g.setParam(vox->id(), "leaf_size", ParamValue{5.0});
    g.connect(load->id(), 0, clean->id(), 0);
    g.connect(clean->id(), 0, vox->id(), 0);
    if (!g.execute()) {
        std::fprintf(stderr, "SMOKE FAILED: %s\n", g.lastError().c_str());
        return 1;
    }
    std::int64_t total = 0;
    if (const auto* out = g.output(vox->id())) {
        for (const auto& obj : out->objects) total += obj->cloud->size();
    }
    std::printf("SMOKE OK points=%lld\n", static_cast<long long>(total));
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
#ifdef PCSEARCH_HAS_VTK
    QSurfaceFormat::setDefaultFormat(QVTKOpenGLNativeWidget::defaultFormat());
#endif
    QApplication app(argc, argv);
    QCoreApplication::setApplicationName("PointCloudSearch");

    QCommandLineParser parser;
    parser.setApplicationDescription("PointCloudSearch desktop application");
    parser.addHelpOption();
    const QCommandLineOption smoke_opt("smoke", "Headless pipeline smoke test", "ply");
    const QCommandLineOption demo_opt("demo", "Open a demo pipeline with <ply>", "ply");
    const QCommandLineOption autoquit_opt("autoquit", "Quit after N seconds", "seconds");
    parser.addOption(smoke_opt);
    parser.addOption(demo_opt);
    parser.addOption(autoquit_opt);
    parser.process(app);

    if (parser.isSet(smoke_opt)) {
        return runSmoke(parser.value(smoke_opt));
    }

    // 默认中文 + 暗色主题；用户在 View 菜单切换。
    app::SimpleTranslator* translator = new app::SimpleTranslator();
    app.installTranslator(translator);
    app::applyTheme(app, true);

    app::MainWindow window;
    window.setLanguageChinese(true);
    if (parser.isSet(demo_opt)) {
        if (!window.loadDemo(parser.value(demo_opt))) {
            std::fprintf(stderr, "DEMO FAILED: cannot load %s\n",
                         parser.value(demo_opt).toUtf8().constData());
            return 1;
        }
        QTimer::singleShot(0, &window, &app::MainWindow::runGraph);
    }
    window.show();
    if (parser.isSet(autoquit_opt)) {
        const int seconds = parser.value(autoquit_opt).toInt();
        if (seconds > 0) {
            QTimer::singleShot(seconds * 1000, &app, &QCoreApplication::quit);
        }
    }
    return app.exec();
}
