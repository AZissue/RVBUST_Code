#include "ViewportManager.h"

namespace rvc {

ViewportManager::ViewportManager(QMainWindow* mainWindow, QObject* parent)
    : QObject(parent), mainWindow_(mainWindow)
{
}

Viewport3D* ViewportManager::ensureViewport(const QString& name)
{
    if (auto it = docks_.find(name); it != docks_.end()) {
        it.value()->show();
        it.value()->raise();
        return qobject_cast<Viewport3D*>(it.value()->widget());
    }

    auto* dock = new QDockWidget(name, mainWindow_);
    dock->setObjectName(QStringLiteral("viewport_dock_%1").arg(name));
    dock->setFeatures(QDockWidget::DockWidgetClosable | QDockWidget::DockWidgetMovable |
                      QDockWidget::DockWidgetFloatable);
    auto* viewport = new Viewport3D(dock);
    viewport->roiPickedCallback = [this](RoiBox roi) {
        if (roiHandler_)
            roiHandler_(roi);
    };
    dock->setWidget(viewport);

    mainWindow_->addDockWidget(Qt::RightDockWidgetArea, dock);
    // 与既有视窗 tab 合并（新视窗置顶）
    if (!docks_.isEmpty())
        mainWindow_->tabifyDockWidget(docks_.last(), dock);
    dock->show();
    dock->raise();

    docks_.insert(name, dock);
    Q_EMIT viewportDockAdded(dock);
    return viewport;
}

void ViewportManager::addViewport()
{
    ++counter_;
    ensureViewport(QStringLiteral("视窗%1").arg(counter_));
}

void ViewportManager::routeDisplay(const std::string& viewport, PointCloud cloud,
                                   DisplayOverlays overlays)
{
    const QString name = viewport.empty() ? QStringLiteral("主视窗")
                                          : QString::fromStdString(viewport);
    ensureViewport(name)->setPointCloud(std::move(cloud), std::move(overlays));
}

} // namespace rvc
