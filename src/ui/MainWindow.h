#pragma once

// 主窗口（无边框 + 自定义暗色标题栏 + 内部 QMainWindow 承载 Dock/菜单/工具栏）。
//   内部：中央 = 流程画布（QtNodes）；Dock = 工具箱（左）、属性（右）、日志/结果（下）、3D 视窗（右，可增删/tab 折叠）
// 「窗口」菜单控制各 Dock 显示/折叠，「添加3D视窗」动态新建视窗。
// 运行为异步（EngineRunner worker 线程），运行中禁用运行按钮。

#include <memory>
#include <QWidget>

#include "core/Solution.h"
#include "core/DataTypes.h"
#include "core/Engine.h"

namespace QtNodes {
class BasicGraphicsScene;
}

class QDockWidget;
class QLabel;
class QMainWindow;
class QMenu;
class QPlainTextEdit;
class QPushButton;
class QTableWidget;
class QToolButton;
class QVBoxLayout;

namespace rvc {

class EngineRunner;
class FlowModel;
class FlowView;
class Toolbox;
class ViewportManager;
class PropertyPanel;

class MainWindow : public QWidget {
    Q_OBJECT
public:
    explicit MainWindow(QWidget* parent = nullptr);
    ~MainWindow() override;

    // 演示链路（--demo 命令行用）：构建带 ROI 的测量流水线并运行一次
    void loadDemoFlow(const QString& plyPath);

protected:
    bool nativeEvent(const QByteArray& eventType, void* message, qintptr* result) override;
    void mouseDoubleClickEvent(QMouseEvent* event) override;
    void closeEvent(QCloseEvent* event) override;

private:
    void setupWorkspace(QMainWindow* w);
    void updateMaximizeButton();
    void runOnce();                       // 触发异步运行
    void onModuleFinished(const ModuleRunRecord& rec);
    void onRunFinished(const RunResult& result, double totalMs);
    void loadSolution();
    void saveSolution();

    // 日志级别（语义色的正当用途）
    enum class LogLevel { Normal, Success, Warning, Error };
    void appendLog(const QString& line, LogLevel level = LogLevel::Normal);
    void fillResultsTable();
    void onSceneSelectionChanged();
    void onRoiPicked(const RoiBox& roi);  // 3D 框选结果回写选中模块 ROI 参数

    Solution solution_;
    // scene_ 必须比 inner_/view_ 晚析构：view 析构时会访问 scene，
    // 因此用 unique_ptr 管理并声明在 inner_ 之前。
    std::unique_ptr<QtNodes::BasicGraphicsScene> scene_;
    QMainWindow* inner_ = nullptr;        // 内部真正承载 Dock/菜单/工具栏的 QMainWindow
    QWidget* titleBar_ = nullptr;
    QLabel* titleLabel_ = nullptr;
    QToolButton* maxButton_ = nullptr;
    FlowModel* flowModel_ = nullptr;
    FlowView* view_ = nullptr;
    Toolbox* toolbox_ = nullptr;
    ViewportManager* viewportManager_ = nullptr;
    PropertyPanel* propertyPanel_ = nullptr;
    EngineRunner* engineRunner_ = nullptr;

    QPlainTextEdit* logView_ = nullptr;
    QTableWidget* resultsTable_ = nullptr;
    QMenu* windowMenu_ = nullptr;
    QAction* runAction_ = nullptr;
    QDockWidget* toolboxDock_ = nullptr;
    QDockWidget* propertyDock_ = nullptr;
    QDockWidget* bottomDock_ = nullptr;

    ModuleBase* selectedModule_ = nullptr;  // 当前画布选中模块（框选 ROI 回写目标）
    RoiBox lastWrittenRoi_;                 // 上次写入的 ROI（交互过程防抖）
    bool doubleClickMax_ = false;           // 标题栏双击最大化标志
};

} // namespace rvc
