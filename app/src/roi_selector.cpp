#include "roi_selector.h"

#ifdef PCSEARCH_HAS_VTK
#include <vtkBoxRepresentation.h>
#include <vtkBoxWidget2.h>
#include <vtkCommand.h>
#include <vtkPoints.h>
#include <vtkPolyData.h>
#include <vtkProperty.h>
#include <vtkRenderWindowInteractor.h>
#include <vtkTransform.h>
#endif

#include <algorithm>
#include <cmath>

namespace app {

namespace {

#ifdef PCSEARCH_HAS_VTK
constexpr double kRadToDeg = 180.0 / 3.14159265358979323846;

// Extract XYZ intrinsic Euler angles (degrees) from an orthonormal rotation
// matrix, matching R = Rz(rz) * Ry(ry) * Rx(rx). Only meaningful away from
// gimbal lock (ry = +/-90 deg).
void eulerFromRotation(const double r[9], double out_deg[3]) {
    // r is column-major 3x3: r[col * 3 + row].
    const double r20 = r[2 * 3 + 0];
    const double r21 = r[2 * 3 + 1];
    const double r22 = r[2 * 3 + 2];
    const double r10 = r[1 * 3 + 0];
    const double r00 = r[0 * 3 + 0];
    const double ry = std::asin(std::clamp(-r20, -1.0, 1.0));
    const double rx = std::atan2(r21, r22);
    const double rz = std::atan2(r10, r00);
    out_deg[0] = rx * kRadToDeg;
    out_deg[1] = ry * kRadToDeg;
    out_deg[2] = rz * kRadToDeg;
}

class RoiCallback final : public vtkCommand {
public:
    static RoiCallback* New() { return new RoiCallback; }
    void Execute(vtkObject*, unsigned long event, void*) override {
        if (!selector_ || !rep_) return;
        if (event == vtkCommand::EndInteractionEvent) {
            emit selector_->roiEditFinished();
            return;
        }
        if (event != vtkCommand::InteractionEvent) return;
        // Read the box pose directly from the hex corners: the representation
        // updates these 8 corners on every translate/scale/rotate, so this is
        // independent of transform decomposition quirks.
        vtkNew<vtkPolyData> pd;
        rep_->GetPolyData(pd);
        vtkPoints* pts = pd->GetPoints();
        if (!pts || pts->GetNumberOfPoints() < 8) return;

        double center[3] = {0.0, 0.0, 0.0};
        for (int i = 0; i < 8; ++i) {
            double p[3];
            pts->GetPoint(i, p);
            center[0] += p[0];
            center[1] += p[1];
            center[2] += p[2];
        }
        center[0] /= 8.0;
        center[1] /= 8.0;
        center[2] /= 8.0;

        double p0[3], p1[3], p3[3], p4[3];
        pts->GetPoint(0, p0);
        pts->GetPoint(1, p1);
        pts->GetPoint(3, p3);
        pts->GetPoint(4, p4);
        const double ex[3] = {p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]};
        const double ey[3] = {p3[0] - p0[0], p3[1] - p0[1], p3[2] - p0[2]};
        const double ez[3] = {p4[0] - p0[0], p4[1] - p0[1], p4[2] - p0[2]};
        const double half[3] = {0.5 * std::sqrt(ex[0] * ex[0] + ex[1] * ex[1] + ex[2] * ex[2]),
                                0.5 * std::sqrt(ey[0] * ey[0] + ey[1] * ey[1] + ey[2] * ey[2]),
                                0.5 * std::sqrt(ez[0] * ez[0] + ez[1] * ez[1] + ez[2] * ez[2])};

        // Rotation matrix columns = normalized local axes.
        double rot[9] = {0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0};
        for (int c = 0; c < 3; ++c) {
            const double* edge = c == 0 ? ex : (c == 1 ? ey : ez);
            const double len = 2.0 * half[c];
            if (len > 1e-12) {
                rot[c * 3 + 0] = edge[0] / len;
                rot[c * 3 + 1] = edge[1] / len;
                rot[c * 3 + 2] = edge[2] / len;
            }
        }
        double euler[3];
        eulerFromRotation(rot, euler);

        emit selector_->roiChanged(center[0], center[1], center[2], half[0],
                                   half[1], half[2], euler[0], euler[1], euler[2]);
    }
    RoiSelector* selector_ = nullptr;
    vtkBoxRepresentation* rep_ = nullptr;
};
#endif

}  // namespace

RoiSelector::RoiSelector(QObject* parent) : QObject(parent) {}

RoiSelector::~RoiSelector() {
#ifdef PCSEARCH_HAS_VTK
    if (widget_) widget_->Off();
    if (widget_) widget_->Delete();
    if (rep_) rep_->Delete();
#endif
}

#ifdef PCSEARCH_HAS_VTK
void RoiSelector::attach(vtkRenderWindowInteractor* interactor) {
    if (widget_) return;
    rep_ = vtkBoxRepresentation::New();
    rep_->SetPlaceFactor(1.0);
    rep_->GetOutlineProperty()->SetColor(0.1, 1.0, 0.3);
    // Thinner outline so the box never occludes the cloud it is framing. The
    // previous 2.0 px looked heavy; 1.2 px is still visible without blocking.
    rep_->GetOutlineProperty()->SetLineWidth(1.2);
    rep_->GetHandleProperty()->SetColor(0.1, 1.0, 0.3);
    rep_->GetSelectedHandleProperty()->SetColor(1.0, 0.85, 0.1);
    // Keep faces barely-tinted so points inside are still readable.
    rep_->GetFaceProperty()->SetOpacity(0.06);
    rep_->GetFaceProperty()->SetColor(0.1, 1.0, 0.3);
    // Kill the "米字" clutter: outline cursor wires (center->corner) and face
    // wires (in-face cross lines) leave only the clean box outline + handles.
    rep_->OutlineCursorWiresOff();
    rep_->OutlineFaceWiresOff();

    widget_ = vtkBoxWidget2::New();
    widget_->SetRepresentation(rep_);
    widget_->SetInteractor(interactor);
    widget_->RotationEnabledOn();
    widget_->TranslationEnabledOn();
    // Disable the "whole widget at once" scaling (right-button drag). It was
    // the source of "drag the box and it always shrinks no matter the direction"
    // because right-button = uniform scale. Face/axis scaling is handled by
    // MoveFaces below, which is the intuitive "grab a face and pull it in/out".
    widget_->ScalingEnabledOff();
    // Enable per-face (per-axis) scaling: grab the spherical handle on a face
    // and drag along that face normal to enlarge/shrink that axis only.
    widget_->MoveFacesEnabledOn();
    // Body left-drag moves the box cleanly; a face handle rescales that axis,
    // an edge handle rotates.

    auto* cb = RoiCallback::New();
    cb->selector_ = this;
    cb->rep_ = rep_;
    widget_->AddObserver(vtkCommand::InteractionEvent, cb);
    widget_->AddObserver(vtkCommand::EndInteractionEvent, cb);
    cb->Delete();
}
#endif

void RoiSelector::setEnabled(bool on) {
    enabled_ = on;
#ifdef PCSEARCH_HAS_VTK
    if (widget_) {
        if (on) {
            widget_->On();
        } else {
            widget_->Off();
        }
    }
#endif
}

void RoiSelector::setBox(double xmin, double ymin, double zmin, double xmax,
                         double ymax, double zmax) {
    const double cx = 0.5 * (xmin + xmax);
    const double cy = 0.5 * (ymin + ymax);
    const double cz = 0.5 * (zmin + zmax);
    setBoxObb(cx, cy, cz, 0.5 * (xmax - xmin), 0.5 * (ymax - ymin),
              0.5 * (zmax - zmin), 0.0, 0.0, 0.0);
}

void RoiSelector::setBoxObb(double cx, double cy, double cz, double hx, double hy,
                            double hz, double rx, double ry, double rz) {
#ifdef PCSEARCH_HAS_VTK
    if (!rep_) return;
    // Place an origin-centered hex, then rotate/translate it to the requested
    // pose. Keeping the placement centered at the origin makes the interaction
    // callback read the center directly from the transform position.
    hx = std::max(hx, 1e-6);
    hy = std::max(hy, 1e-6);
    hz = std::max(hz, 1e-6);
    double bounds[6] = {-hx, hx, -hy, hy, -hz, hz};
    rep_->PlaceWidget(bounds);

    // world = T(c) * Rz(rz) * Ry(ry) * Rx(rx) * local.
    vtkNew<vtkTransform> t;
    // VTK's PreMultiply composes M = M * O, so the calls below build
    // M = T(c) * Rz * Ry * Rx (translation is applied first, then rotation).
    t->PreMultiply();
    t->Translate(cx, cy, cz);
    t->RotateZ(rz);
    t->RotateY(ry);
    t->RotateX(rx);
    rep_->SetTransform(t);
#else
    (void)cx;
    (void)cy;
    (void)cz;
    (void)hx;
    (void)hy;
    (void)hz;
    (void)rx;
    (void)ry;
    (void)rz;
#endif
}

}  // namespace app
