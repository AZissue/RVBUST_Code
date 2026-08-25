#pragma once

#include "pcsearch/core_data/object.h"

#include <QWidget>

#include <cstdint>
#include <vector>

class QLabel;
class QShortcut;

#ifdef PCSEARCH_HAS_VTK
class QVTKOpenGLNativeWidget;
class vtkRenderer;
class vtkActor;
class vtkProp;
#endif

namespace app {
class RoiSelector;
}

namespace app {

class PointCloudView : public QWidget {
    Q_OBJECT
public:
    explicit PointCloudView(QWidget* parent = nullptr);

    // Uniform display-decimation stride for `n` points: keeps the displayed
    // point count <= kMaxDisplayPoints (GPU-friendly on integrated graphics).
    static std::int64_t displayStride(std::int64_t n) {
        return n > kMaxDisplayPoints
                   ? (n + kMaxDisplayPoints - 1) / kMaxDisplayPoints
                   : 1;
    }
    static std::int64_t displayCount(std::int64_t n) {
        const std::int64_t s = displayStride(n);
        return n / s + (n % s ? 1 : 0);
    }

    void showObjectList(const pcsearch::core::ObjectList* list);
    void clearView();
    // Toggle interactive ROI box editing. When enabled, dragging the box emits
    // roiEdited with (center, half extents, Euler angles in degrees).
    void enableRoiEdit(bool on, const double bounds[6] = nullptr);
    void enableRoiEditObb(bool on, const double center[3], const double half[3],
                          const double rot_deg[3]);
    // While in interactive ROI editing, toggle whether the box responds to the
    // mouse. `true` (shortcut W) lets you drag/scale/rotate the box; `false`
    // (shortcut E) keeps the box visible for reference but lets you orbit/zoom/
    // pan the cloud without accidentally moving it.
    void setRoiBoxOperable(bool on);
    // Persistent wireframe box (used by Box ROI node preview / selection).
    // AABB overload keeps rotation at zero.
    void showRoiBox(double xmin, double ymin, double zmin, double xmax, double ymax,
                    double zmax);
    void showRoiBoxObb(const double center[3], const double half[3],
                       const double rot_deg[3]);
    void hideRoiBox();
    // Reset the camera to frame everything currently in the scene (cloud +
    // ROI box) so the box is easy to find after a reset / edit toggle.
    void frameScene();

signals:
    // center (mm) + half extents (mm) + XYZ intrinsic Euler angles (deg).
    void roiEdited(double cx, double cy, double cz, double hx, double hy, double hz,
                   double rx, double ry, double rz);
    // Fired once when the user releases the mouse after an ROI edit.
    void roiEditFinished();
    // Non-blocking status message about what the view did (e.g. display
    // decimation), shown in the application log.
    void displayInfo(const QString& message);

private:
    static constexpr std::int64_t kMaxDisplayPoints = 1500000;
#ifdef PCSEARCH_HAS_VTK
    void clearCloudActors();
#endif
    QLabel* placeholder_ = nullptr;
#ifdef PCSEARCH_HAS_VTK
    QVTKOpenGLNativeWidget* vtk_widget_ = nullptr;
    vtkRenderer* renderer_ = nullptr;
    vtkActor* roi_box_actor_ = nullptr;
    std::vector<vtkProp*> cloud_actors_;
#endif
    RoiSelector* roi_selector_ = nullptr;
    // W/E shortcuts enabled only while interactive ROI editing is active, so a
    // bare "w" outside editing still reaches the camera style (VTK uses 'w'
    // for wire-frame) and typing into parameter fields is unaffected.
    QShortcut* roi_box_work_shortcut_ = nullptr;
    QShortcut* roi_box_end_shortcut_ = nullptr;
    // True while interactive ROI editing (vtkBoxWidget2) is active. When set,
    // showRoiBoxObb() skips drawing the static wireframe preview actor so the
    // scene shows only the interaction box (one box, not two).
    bool roi_editing_ = false;
    // Current operable state of the ROI box while editing (mirrors
    // RoiSelector::setOperable); reset to true whenever edit mode is entered.
    bool roi_box_operable_ = true;
};

}  // namespace app
