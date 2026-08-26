#pragma once

#include "pcsearch/core_data/object.h"

#include <QString>
#include <QStringList>
#include <QWidget>

#include <cstdint>
#include <map>
#include <vector>

class QLabel;
class QShortcut;

#ifdef PCSEARCH_HAS_VTK
#include <vtkSmartPointer.h>

class QVTKOpenGLNativeWidget;
class vtkRenderer;
class vtkActor;
class vtkInteractorStyleTrackballCamera;
class vtkProp;
#endif

namespace app {
class RoiSelector;
}

namespace app {

// Display density tier (PROJECT §8.6). Low keeps the historical red line of
// ~1.5M displayed points per object (integrated graphics / remote desktop);
// higher tiers raise the per-object cap for stronger machines. The viewport
// capacity budget (30M points) is enforced independently as a warning.
enum class HardwareTier { Low, Standard, High };

class PointCloudView : public QWidget {
    Q_OBJECT
public:
    explicit PointCloudView(QWidget* parent = nullptr);

    // Uniform display-decimation stride for `n` points: keeps the displayed
    // point count <= the tier's per-object cap (GPU-friendly on integrated
    // graphics). The no-tier overloads keep the historical Low default.
    static std::int64_t displayStride(std::int64_t n) {
        return displayStride(n, HardwareTier::Low);
    }
    static std::int64_t displayCount(std::int64_t n) {
        return displayCount(n, HardwareTier::Low);
    }
    // Per-object displayed-point cap for a hardware tier.
    static std::int64_t maxDisplayPointsForTier(HardwareTier tier) {
        switch (tier) {
            case HardwareTier::Low: return 1500000;
            case HardwareTier::Standard: return 3000000;
            case HardwareTier::High: return 10000000;
        }
        return 1500000;
    }
    static std::int64_t displayStride(std::int64_t n, HardwareTier tier) {
        const std::int64_t cap = maxDisplayPointsForTier(tier);
        return n > cap ? (n + cap - 1) / cap : 1;
    }
    static std::int64_t displayCount(std::int64_t n, HardwareTier tier) {
        const std::int64_t s = displayStride(n, tier);
        return n / s + (n % s ? 1 : 0);
    }
    // Viewport capacity budget: total displayed points across all layers
    // (camera ~5MP x 6 frames). Exceeding it warns instead of dropping data.
    static constexpr std::int64_t kViewportPointBudget = 30000000;
    // Remote-desktop sessions are treated as Low tier; local machines report
    // Standard. The view does not auto-apply the result yet (LOD is future
    // work), callers can query it when a tier switch UI is added.
    static HardwareTier detectHardwareTier();
    HardwareTier hardwareTier() const { return tier_; }
    void setHardwareTier(HardwareTier tier) { tier_ = tier; }

    // Layer for the node-selection display. routeDisplayNodes clears it on
    // viewports that have display3d layers (display3d wins, historical UX).
    static QString selectionLayerId() { return QStringLiteral("selection"); }

    // Multi-layer display (PROJECT §8.7): one layer per display3d node.
    // Updating an existing layer rebuilds only that layer's actors; other
    // layers keep their data. Layer creation order = stacking order.
    void setDisplayLayer(const QString& layer_id,
                         const pcsearch::core::ObjectList* list);
    void clearDisplayLayer(const QString& layer_id);
    void clearAllDisplayLayers();
    QStringList displayLayers() const;

    void showObjectList(const pcsearch::core::ObjectList* list);
    void clearView();
    // Display-type filter ("Show Data Types"): which object kinds the view
    // renders. Clouds are point objects; boxes are valid RoiBox wireframes;
    // lines are reserved for future geometry. All default to visible.
    void setVisibleKinds(bool cloud, bool box, bool line);
    bool cloudVisible() const { return cloud_visible_; }
    bool boxVisible() const { return box_visible_; }
    bool lineVisible() const { return line_visible_; }
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

    // ---- Per-frame display transform tool (translate / rotate) ----
    // One frame is identified by (provenance, frame name); transforms survive
    // re-runs within the session (re-applied by key when actors are rebuilt).
    struct FrameRef {
        QString source;  // producing node id (object provenance)
        QString frame;   // object / frame name
    };
    // Enables the Move/Rotate tool: left-drag translates the current target
    // frames in the camera plane, right-drag rotates them around the camera
    // axes (through each frame's center). Off restores camera navigation.
    void setTransformToolActive(bool on);
    bool transformToolActive() const { return transform_tool_active_; }
    // Frames the tool acts on (set from the properties-panel selection).
    void setTransformTargets(const std::vector<FrameRef>& frames);
    const std::vector<FrameRef>& transformTargets() const {
        return transform_targets_;
    }
    // Incremental world-space translation (mm) applied to `frames`.
    void applyFrameTranslation(const std::vector<FrameRef>& frames,
                               const Eigen::Vector3f& delta);
    // Incremental rotation (degrees) around `axis` (world space), through
    // each frame's own center.
    void applyFrameRotation(const std::vector<FrameRef>& frames,
                            float angle_deg, const Eigen::Vector3f& axis);
    void resetFrameTransforms(const std::vector<FrameRef>& frames);
    // Number of frames carrying a non-identity transform (UI feedback/tests).
    std::size_t transformedFrameCount() const;
    // Internal drag helpers used by the tool's interactor style.
    void applyDragTranslation(int dx_px, int dy_px);
    void applyDragRotation(int dx_px, int dy_px);

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
    struct FrameTransform {
        Eigen::Vector3f translation = Eigen::Vector3f::Zero();
        Eigen::Matrix3f rotation = Eigen::Matrix3f::Identity();
        bool has() const {
            return translation.squaredNorm() > 1e-12f ||
                   !rotation.isIdentity(1e-9f);
        }
    };
#ifdef PCSEARCH_HAS_VTK
    // Build point/color actors for `list` into `actors`; returns the number
    // of points actually displayed (after tier-based decimation).
    std::int64_t buildCloudActors(const pcsearch::core::ObjectList& list,
                                  std::vector<vtkSmartPointer<vtkProp>>& actors);
    void addRoiBoxActor(const pcsearch::core::RoiBox& roi,
                        const Eigen::Vector3f& frame_center,
                        const FrameTransform* tf,
                        std::vector<vtkSmartPointer<vtkProp>>& actors);
    void removeLayerActors(std::vector<vtkSmartPointer<vtkProp>>& actors);
    void reorderActors();
    void enforceViewportBudget();
    void rebuildSelectionLayer();
#endif
    const FrameTransform* frameTransform(const QString& source,
                                         const QString& frame) const;
    Eigen::Vector3f frameCenter(const pcsearch::core::PointCloudObject& obj) const;
    struct DisplayLayer {
        QString id;
        bool camera_fitted = false;
        std::int64_t shown_points = 0;
#ifdef PCSEARCH_HAS_VTK
        // Smart pointers keep every actor alive across remove/re-add, so
        // reordering layers can remove actors from the renderer (releasing
        // its reference) and add them back without dangling pointers.
        std::vector<vtkSmartPointer<vtkProp>> actors;
#endif
    };
    QLabel* placeholder_ = nullptr;
#ifdef PCSEARCH_HAS_VTK
    QVTKOpenGLNativeWidget* vtk_widget_ = nullptr;
    vtkRenderer* renderer_ = nullptr;
    vtkActor* roi_box_actor_ = nullptr;
    // Interactor styles: camera navigation (left-rotate/right-pan/wheel-zoom)
    // vs the Move/Rotate tool (left-drag translate, right-drag rotate).
    vtkSmartPointer<vtkInteractorStyleTrackballCamera> camera_style_;
    vtkSmartPointer<vtkInteractorStyleTrackballCamera> transform_style_;
#endif
    std::vector<DisplayLayer> layers_;
    std::map<std::pair<QString, QString>, FrameTransform> frame_transforms_;
    std::vector<FrameRef> transform_targets_;
    bool transform_tool_active_ = false;
    HardwareTier tier_ = HardwareTier::Low;
    bool cloud_visible_ = true;
    bool box_visible_ = true;
    bool line_visible_ = true;
    bool budget_exceeded_ = false;
    pcsearch::core::ObjectList last_selection_;
    bool has_last_selection_ = false;
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
