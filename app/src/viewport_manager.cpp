#include "viewport_manager.h"

#include "point_cloud_view.h"

#include <QDockWidget>
#include <QMainWindow>

namespace app {

ViewportManager::ViewportManager(QMainWindow* window, QObject* parent)
    : QObject(parent), window_(window) {}

void ViewportManager::setMainViewport(PointCloudView* view) { main_ = view; }

PointCloudView* ViewportManager::viewport(const QString& name) {
    const QString key = name.isEmpty() ? QStringLiteral("Main") : name;
    if (key == QStringLiteral("Main")) return main_;
    const auto it = viewports_.find(key);
    if (it != viewports_.end()) return it->second.second;

    auto* dock = new QDockWidget(key, window_);
    auto* view = new PointCloudView(dock);
    dock->setWidget(view);
    window_->addDockWidget(Qt::RightDockWidgetArea, dock);
    viewports_[key] = {dock, view};
    return view;
}

QStringList ViewportManager::names() const {
    QStringList out;
    out << QStringLiteral("Main");
    for (const auto& entry : viewports_) {
        out << entry.first;
    }
    return out;
}

QString ViewportManager::addViewport(const QString& preferred_name) {
    QString name = preferred_name;
    if (name.isEmpty()) name = QStringLiteral("Viewport %1").arg(counter_);
    while (name == QStringLiteral("Main") || viewports_.count(name)) {
        name = QStringLiteral("Viewport %1").arg(counter_++);
    }
    viewport(name);
    return name;
}

}  // namespace app
