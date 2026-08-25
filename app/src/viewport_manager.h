#pragma once

#include <QObject>
#include <QString>
#include <QStringList>

#include <map>
#include <utility>

class QDockWidget;
class QMainWindow;

namespace app {

class PointCloudView;

// Named, dockable 3D viewports. "Main" resolves to the central viewport;
// any other name creates a dock widget on demand (used by Display 3D nodes).
class ViewportManager : public QObject {
    Q_OBJECT
public:
    explicit ViewportManager(QMainWindow* window, QObject* parent = nullptr);

    void setMainViewport(PointCloudView* view);
    PointCloudView* viewport(const QString& name);
    QStringList names() const;
    QString addViewport(const QString& preferred_name = {});

private:
    QMainWindow* window_ = nullptr;
    PointCloudView* main_ = nullptr;
    std::map<QString, std::pair<QDockWidget*, PointCloudView*>> viewports_;
    int counter_ = 1;
};

}  // namespace app
