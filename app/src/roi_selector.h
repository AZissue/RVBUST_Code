#pragma once

#include <QObject>

#ifdef PCSEARCH_HAS_VTK
class vtkBoxWidget2;
class vtkBoxRepresentation;
class vtkRenderWindowInteractor;
#endif

namespace app {

// Reusable interactive ROI box selector (vtkBoxWidget2). Any 3D viewport can
// attach one and drive it with setEnabled/setBoxObb; dragging emits
// roiChanged with the current box as (center, half extents, Euler angles deg).
// The box is a full oriented box: translation, corner-handle scaling and
// rotation are supported.
class RoiSelector : public QObject {
    Q_OBJECT
public:
    explicit RoiSelector(QObject* parent = nullptr);
    ~RoiSelector() override;

#ifdef PCSEARCH_HAS_VTK
    void attach(vtkRenderWindowInteractor* interactor);
#endif
    void setEnabled(bool on);
    // Toggle whether the box responds to the mouse. When off the box stays
    // visible (so you can still see what you are framing) but ignores all
    // interaction events, letting the camera style drive rotate/zoom/pan even
    // when the cursor is over the box. Used by the Box ROI view shortcut keys.
    void setOperable(bool on);
    bool enabled() const { return enabled_; }
    // Convenience: axis-aligned box in scene units
    // (xmin,ymin,zmin,xmax,ymax,zmax order).
    void setBox(double xmin, double ymin, double zmin, double xmax, double ymax,
                double zmax);
    // Oriented box: world center + half extents (local axes) + XYZ intrinsic
    // Euler angles in degrees (R = Rz(rz) * Ry(ry) * Rx(rx)).
    void setBoxObb(double cx, double cy, double cz, double hx, double hy, double hz,
                   double rx, double ry, double rz);

signals:
    // center (mm) + half extents (mm) + rotation angles (deg).
    void roiChanged(double cx, double cy, double cz, double hx, double hy, double hz,
                    double rx, double ry, double rz);
    // Fired once when an interactive edit finishes (mouse release), so the UI
    // can refresh panels/preview/log without doing it on every mouse move.
    void roiEditFinished();

private:
#ifdef PCSEARCH_HAS_VTK
    vtkBoxWidget2* widget_ = nullptr;
    vtkBoxRepresentation* rep_ = nullptr;
#endif
    bool enabled_ = false;
};

}  // namespace app
