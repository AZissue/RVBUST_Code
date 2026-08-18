#pragma once

// 视窗管理器：管理多个 3D 视窗 Dock（可添加/关闭/折叠），
// 并按视窗名路由 Display3D 模块的显示回调。

#include <QDockWidget>
#include <QMainWindow>
#include <QMap>
#include <QObject>
#include <QString>

#include "Viewport3D.h"
#include "core/DataTypes.h"
#include "modules/display/Display3DModule.h"

namespace rvc {

class ViewportManager : public QObject {
    Q_OBJECT
public:
    explicit ViewportManager(QMainWindow* mainWindow, QObject* parent = nullptr);

    // 取指定名字的视窗；不存在则自动创建（tab 到既有视窗上）
    Viewport3D* ensureViewport(const QString& name);

    // 「窗口」菜单「添加3D视窗」：按 视窗2/视窗3... 命名创建并置顶
    void addViewport();

    // 显示回调路由入口（GUI 线程调用）
    void routeDisplay(const std::string& viewport, PointCloud cloud, DisplayOverlays overlays);

    // 框选 ROI 回调统一注入（每个视窗共用同一处理）
    void setRoiPickedHandler(std::function<void(RoiBox)> handler) { roiHandler_ = std::move(handler); }

Q_SIGNALS:
    // 新视窗 Dock 创建（MainWindow 把 toggleViewAction 挂进窗口菜单）
    void viewportDockAdded(QDockWidget* dock);

private:
    QMainWindow* mainWindow_;
    QMap<QString, QDockWidget*> docks_;
    std::function<void(RoiBox)> roiHandler_;
    int counter_ = 1;  // 视窗N 计数（主视窗=1）
};

} // namespace rvc
