#include "point_cloud_view.h"

#include "roi_selector.h"

#include <QLabel>
#include <QShortcut>
#include <QVBoxLayout>

#ifdef PCSEARCH_HAS_VTK
#include <vtkActor.h>
#include <vtkAxesActor.h>
#include <vtkCamera.h>
#include <vtkCellArray.h>
#include <vtkCommand.h>
#include <vtkCubeSource.h>
#include <vtkDataSetMapper.h>
#include <vtkInteractorStyleTrackballCamera.h>
#include <vtkNew.h>
#include <vtkObjectFactory.h>
#include <vtkPoints.h>
#include <vtkPointData.h>
#include <vtkPolyData.h>
#include <vtkPolyDataMapper.h>
#include <vtkProperty.h>
#include <vtkRenderWindow.h>
#include <vtkRenderWindowInteractor.h>
#include <vtkRenderer.h>
#include <vtkTransform.h>
#include <vtkTransformPolyDataFilter.h>
#include <vtkUnsignedCharArray.h>
#include <QVTKOpenGLNativeWidget.h>
#endif

#include <algorithm>
#include <cmath>

#ifdef _WIN32
#include <windows.h>
#endif

namespace {

// RVC Manager-style camera navigation: left button rotates, wheel zooms and the
// *right* button pans. vtkInteractorStyleTrackballCamera defaults to middle
// button pan and right button dolly, so remap right -> pan here.
class CameraStylePanRight final : public vtkInteractorStyleTrackballCamera {
public:
    static CameraStylePanRight* New() {
        auto* s = new CameraStylePanRight;
        s->InitializeObjectBase();
        return s;
    }
    vtkTypeMacro(CameraStylePanRight, vtkInteractorStyleTrackballCamera);

    void OnRightButtonDown() override { this->OnMiddleButtonDown(); }
    void OnRightButtonUp() override { this->OnMiddleButtonUp(); }

    // A slightly bigger wheel step than the default 1.1 so zooming deep into a
    // cloud does not feel like it needs many notches per step.
    void OnMouseWheelForward() override { this->Dolly(1.25); }
    void OnMouseWheelBackward() override { this->Dolly(1.0 / 1.25); }

private:
    CameraStylePanRight() = default;
};

}  // namespace

namespace app {

HardwareTier PointCloudView::detectHardwareTier() {
#ifdef _WIN32
    if (GetSystemMetrics(SM_REMOTESESSION) != 0) return HardwareTier::Low;
#endif
    return HardwareTier::Standard;
}

PointCloudView::PointCloudView(QWidget* parent) : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
#ifdef PCSEARCH_HAS_VTK
    vtk_widget_ = new QVTKOpenGLNativeWidget(this);
    layout->addWidget(vtk_widget_);
    renderer_ = vtkRenderer::New();
    renderer_->SetBackground(0.16, 0.16, 0.18);
    vtk_widget_->renderWindow()->AddRenderer(renderer_);
    vtkNew<CameraStylePanRight> style;
    vtk_widget_->renderWindow()->GetInteractor()->SetInteractorStyle(style);
    roi_selector_ = new RoiSelector(this);
    roi_selector_->attach(vtk_widget_->renderWindow()->GetInteractor());
    // Box ROI view-only shortcut keys: W = operable (drag/scale/rotate the
    // box), E = not operable (free camera, box stays as a reference overlay).
    // Bound to this widget subtree so typing W/E into parameter fields is
    // unaffected. They are no-ops unless ROI editing is active.
    roi_box_work_shortcut_ = new QShortcut(QKeySequence(Qt::Key_W), this);
    roi_box_work_shortcut_->setContext(Qt::WidgetWithChildrenShortcut);
    roi_box_work_shortcut_->setEnabled(false);
    connect(roi_box_work_shortcut_, &QShortcut::activated, this,
            [this] { setRoiBoxOperable(true); });
    roi_box_end_shortcut_ = new QShortcut(QKeySequence(Qt::Key_E), this);
    roi_box_end_shortcut_->setContext(Qt::WidgetWithChildrenShortcut);
    roi_box_end_shortcut_->setEnabled(false);
    connect(roi_box_end_shortcut_, &QShortcut::activated, this,
            [this] { setRoiBoxOperable(false); });
    connect(roi_selector_, &RoiSelector::roiChanged, this,
            &PointCloudView::roiEdited);
    connect(roi_selector_, &RoiSelector::roiEditFinished, this,
            &PointCloudView::roiEditFinished);
#else
    placeholder_ = new QLabel(tr("3D View (VTK not built yet)"), this);
    placeholder_->setAlignment(Qt::AlignCenter);
    layout->addWidget(placeholder_);
#endif
}

void PointCloudView::clearView() {
#ifdef PCSEARCH_HAS_VTK
    enableRoiEdit(false);
    hideRoiBox();
    clearAllDisplayLayers();
    vtk_widget_->renderWindow()->Render();
#else
    clearAllDisplayLayers();
#endif
}

void PointCloudView::enableRoiEdit(bool on, const double bounds[6]) {
    if (!on || !bounds) {
        enableRoiEditObb(on, nullptr, nullptr, nullptr);
        return;
    }
    const double center[3] = {0.5 * (bounds[0] + bounds[1]),
                              0.5 * (bounds[2] + bounds[3]),
                              0.5 * (bounds[4] + bounds[5])};
    const double half[3] = {0.5 * (bounds[1] - bounds[0]),
                            0.5 * (bounds[3] - bounds[2]),
                            0.5 * (bounds[5] - bounds[4])};
    const double rot[3] = {0.0, 0.0, 0.0};
    enableRoiEditObb(on, center, half, rot);
}

void PointCloudView::enableRoiEditObb(bool on, const double center[3],
                                      const double half[3],
                                      const double rot_deg[3]) {
#ifdef PCSEARCH_HAS_VTK
    if (!roi_selector_) return;
    roi_editing_ = on;
    if (on) {
        // The vtkBoxWidget2 renders its own box (outline + handles + translucent
        // faces) once enabled. The static preview actor would otherwise leave a
        // second, overlapping box in the scene while the user drags, so hide it
        // on entry and let the interaction box be the only visible box.
        hideRoiBox();
        if (center && half && rot_deg) {
            roi_selector_->setBoxObb(center[0], center[1], center[2], half[0], half[1],
                                     half[2], rot_deg[0], rot_deg[1], rot_deg[2]);
        }
        // Entering edit mode always starts with an operable box.
        roi_box_operable_ = true;
        roi_selector_->setOperable(true);
        if (roi_box_work_shortcut_) roi_box_work_shortcut_->setEnabled(true);
        if (roi_box_end_shortcut_) roi_box_end_shortcut_->setEnabled(true);
    } else {
        if (roi_box_work_shortcut_) roi_box_work_shortcut_->setEnabled(false);
        if (roi_box_end_shortcut_) roi_box_end_shortcut_->setEnabled(false);
    }
    roi_selector_->setEnabled(on);
    vtk_widget_->renderWindow()->Render();
#else
    (void)on;
    (void)center;
    (void)half;
    (void)rot_deg;
#endif
}

void PointCloudView::setRoiBoxOperable(bool on) {
#ifdef PCSEARCH_HAS_VTK
    if (!roi_selector_ || !roi_editing_ || on == roi_box_operable_) return;
    roi_box_operable_ = on;
    roi_selector_->setOperable(on);
    emit displayInfo(on ? tr("Box ROI：按 W，已启用包围盒操作")
                        : tr("Box ROI：按 E，已禁用包围盒操作（仅查看点云）"));
#else
    (void)on;
#endif
}

void PointCloudView::showRoiBox(double xmin, double ymin, double zmin, double xmax,
                                double ymax, double zmax) {
    const double center[3] = {0.5 * (xmin + xmax), 0.5 * (ymin + ymax),
                              0.5 * (zmin + zmax)};
    const double half[3] = {0.5 * (xmax - xmin), 0.5 * (ymax - ymin),
                            0.5 * (zmax - zmin)};
    const double rot[3] = {0.0, 0.0, 0.0};
    showRoiBoxObb(center, half, rot);
}

void PointCloudView::showRoiBoxObb(const double center[3], const double half[3],
                                   const double rot_deg[3]) {
#ifdef PCSEARCH_HAS_VTK
    if (!renderer_) return;
    // While interactive ROI editing is active the vtkBoxWidget2 is the only box
    // shown; never draw the static wireframe preview on top of it.
    if (roi_editing_) return;
    hideRoiBox();
    vtkNew<vtkCubeSource> cube;
    cube->SetCenter(0.0, 0.0, 0.0);
    cube->SetXLength(std::max(0.002, 2.0 * half[0]));
    cube->SetYLength(std::max(0.002, 2.0 * half[1]));
    cube->SetZLength(std::max(0.002, 2.0 * half[2]));

    vtkNew<vtkTransform> transform;
    transform->PreMultiply();
    transform->Translate(center[0], center[1], center[2]);
    transform->RotateZ(rot_deg[2]);
    transform->RotateY(rot_deg[1]);
    transform->RotateX(rot_deg[0]);
    vtkNew<vtkTransformPolyDataFilter> tf;
    tf->SetTransform(transform);
    tf->SetInputConnection(cube->GetOutputPort());

    vtkNew<vtkPolyDataMapper> mapper;
    mapper->SetInputConnection(tf->GetOutputPort());
    roi_box_actor_ = vtkActor::New();
    roi_box_actor_->SetMapper(mapper);
    roi_box_actor_->GetProperty()->SetColor(0.16, 0.84, 0.35);
    roi_box_actor_->GetProperty()->SetRepresentationToWireframe();
    roi_box_actor_->GetProperty()->SetLineWidth(2.0);
    renderer_->AddActor(roi_box_actor_);
    vtk_widget_->renderWindow()->Render();
#else
    (void)center;
    (void)half;
    (void)rot_deg;
#endif
}

void PointCloudView::hideRoiBox() {
#ifdef PCSEARCH_HAS_VTK
    if (roi_box_actor_) {
        renderer_->RemoveActor(roi_box_actor_);
        roi_box_actor_->Delete();
        roi_box_actor_ = nullptr;
        vtk_widget_->renderWindow()->Render();
    }
#endif
}

void PointCloudView::frameScene() {
#ifdef PCSEARCH_HAS_VTK
    if (!renderer_) return;
    renderer_->ResetCamera();
    vtk_widget_->renderWindow()->Render();
#endif
}

void PointCloudView::clearAllDisplayLayers() {
#ifdef PCSEARCH_HAS_VTK
    for (auto& layer : layers_) removeLayerActors(layer.actors);
#endif
    layers_.clear();
}

void PointCloudView::clearDisplayLayer(const QString& layer_id) {
    const auto it = std::find_if(layers_.begin(), layers_.end(),
                                 [&](const DisplayLayer& l) { return l.id == layer_id; });
    if (it == layers_.end()) return;
#ifdef PCSEARCH_HAS_VTK
    removeLayerActors(it->actors);
#endif
    layers_.erase(it);
#ifdef PCSEARCH_HAS_VTK
    reorderActors();
    vtk_widget_->renderWindow()->Render();
#endif
}

QStringList PointCloudView::displayLayers() const {
    QStringList out;
    for (const auto& layer : layers_) out << layer.id;
    return out;
}

void PointCloudView::setDisplayLayer(const QString& layer_id,
                                     const pcsearch::core::ObjectList* list) {
    if (!list) {
        clearDisplayLayer(layer_id);
        return;
    }
    auto it = std::find_if(layers_.begin(), layers_.end(),
                           [&](const DisplayLayer& l) { return l.id == layer_id; });
    const bool is_new = it == layers_.end();
    if (is_new) {
        DisplayLayer layer;
        layer.id = layer_id;
        layers_.push_back(std::move(layer));
        it = layers_.end() - 1;
    }
#ifdef PCSEARCH_HAS_VTK
    removeLayerActors(it->actors);
    const std::int64_t shown = buildCloudActors(*list, it->actors);
    it->shown_points = shown;
    reorderActors();
    if (is_new || !it->camera_fitted) {
        renderer_->ResetCamera();
        renderer_->GetActiveCamera()->SetClippingRange(0.1, 1e7);
        it->camera_fitted = true;
    }
    vtk_widget_->renderWindow()->Render();
    enforceViewportBudget();
    if (is_new && shown > 0) {
        const std::int64_t total = [&]() {
            std::int64_t t = 0;
            for (const auto& obj : list->objects) t += obj->cloud->size();
            return t;
        }();
        if (shown < total) {
            emit displayInfo(tr("Display decimated: showing %1 of %2 points")
                                 .arg(shown)
                                 .arg(total));
        }
    }
#endif
}

void PointCloudView::showObjectList(const pcsearch::core::ObjectList* list) {
#ifdef PCSEARCH_HAS_VTK
    if (!list) {
        clearView();
        return;
    }
    clearAllDisplayLayers();
    DisplayLayer layer;
    layer.id = selectionLayerId();
    try {
        layer.shown_points = buildCloudActors(*list, layer.actors);
        const std::int64_t shown = layer.shown_points;
        if (shown > 0) {
            layers_.push_back(std::move(layer));
            renderer_->ResetCamera();
            renderer_->GetActiveCamera()->SetClippingRange(0.1, 1e7);
        }
        vtk_widget_->renderWindow()->Render();
        enforceViewportBudget();
        std::int64_t total_points = 0;
        for (const auto& obj : list->objects) total_points += obj->cloud->size();
        if (shown < total_points) {
            emit displayInfo(tr("Display decimated: showing %1 of %2 points")
                                 .arg(shown)
                                 .arg(total_points));
        }
    } catch (const std::exception& e) {
        emit displayInfo(QString::fromUtf8(e.what()));
    } catch (...) {
        emit displayInfo(tr("Display failed (unknown error)"));
    }
#else
    (void)list;
#endif
}

std::int64_t PointCloudView::buildCloudActors(
    const pcsearch::core::ObjectList& list,
    std::vector<vtkSmartPointer<vtkProp>>& actors) {
#ifdef PCSEARCH_HAS_VTK
    if (!renderer_) return 0;
    std::int64_t shown_points = 0;
    for (const auto& obj : list.objects) {
        const auto& cloud = *obj->cloud;
        const std::int64_t n = cloud.size();
        if (n <= 0) continue;

        // Display decimation: huge clouds (RVC 5MP / stitched 10M+) must
        // not be uploaded to the GPU in full on integrated graphics or
        // over remote desktop - building double-precision VTK arrays on
        // the UI thread then rendering freezes the app and can crash the
        // GL driver. Uniform stride keeps the outline while capping GPU
        // work at the active hardware tier. The pipeline data is never
        // modified, only the view.
        const std::int64_t stride = displayStride(n, tier_);
        const std::int64_t count = displayCount(n, tier_);
        shown_points += count;

        vtkNew<vtkPoints> points;
        points->SetDataTypeToFloat();
        points->SetNumberOfPoints(count);
        vtkNew<vtkCellArray> verts;
        verts->AllocateEstimate(count, 1);
        verts->InsertNextCell(count);
        std::int64_t out = 0;
        for (std::int64_t i = 0; i < n; i += stride, ++out) {
            points->SetPoint(static_cast<vtkIdType>(out), cloud.points(i, 0),
                             cloud.points(i, 1), cloud.points(i, 2));
            verts->InsertCellPoint(static_cast<vtkIdType>(out));
        }

        vtkNew<vtkPolyData> poly;
        poly->SetPoints(points);
        poly->SetVerts(verts);

        if (cloud.hasColors()) {
            vtkNew<vtkUnsignedCharArray> colors;
            colors->SetNumberOfComponents(3);
            colors->SetName("RGB");
            colors->SetNumberOfTuples(count);
            out = 0;
            for (std::int64_t i = 0; i < n; i += stride, ++out) {
                unsigned char rgb[3] = {
                    static_cast<unsigned char>(cloud.colors(i, 0) * 255.0 + 0.5),
                    static_cast<unsigned char>(cloud.colors(i, 1) * 255.0 + 0.5),
                    static_cast<unsigned char>(cloud.colors(i, 2) * 255.0 + 0.5)};
                colors->SetTypedTuple(static_cast<vtkIdType>(out), rgb);
            }
            poly->GetPointData()->SetScalars(colors);
        }

        vtkNew<vtkPolyDataMapper> mapper;
        mapper->SetInputData(poly);
        vtkNew<vtkActor> actor;
        actor->SetMapper(mapper);
        if (!cloud.hasColors()) {
            actor->GetProperty()->SetColor(obj->display_color.x(),
                                           obj->display_color.y(),
                                           obj->display_color.z());
        }
        renderer_->AddActor(actor);
        actors.push_back(vtkSmartPointer<vtkProp>(actor));
    }
    return shown_points;
#else
    (void)list;
    (void)actors;
    return 0;
#endif
}

void PointCloudView::removeLayerActors(
    std::vector<vtkSmartPointer<vtkProp>>& actors) {
#ifdef PCSEARCH_HAS_VTK
    if (!renderer_) return;
    for (const auto& actor : actors) {
        // Drop the renderer's reference only; the layer's smart pointers keep
        // the actor alive so it can be re-added when layers are reordered.
        renderer_->RemoveViewProp(actor);
    }
    actors.clear();
#else
    (void)actors;
#endif
}

void PointCloudView::reorderActors() {
#ifdef PCSEARCH_HAS_VTK
    if (!renderer_) return;
    // Re-add every layer actor in layer order so refreshing one layer does not
    // move it above the others (creation order = stacking order, §8.7).
    for (auto& layer : layers_) {
        for (const auto& actor : layer.actors) renderer_->RemoveViewProp(actor);
    }
    for (auto& layer : layers_) {
        for (const auto& actor : layer.actors) renderer_->AddViewProp(actor);
    }
#endif
}

void PointCloudView::enforceViewportBudget() {
#ifdef PCSEARCH_HAS_VTK
    std::int64_t total = 0;
    for (const auto& layer : layers_) total += layer.shown_points;
    if (total > kViewportPointBudget && !budget_exceeded_) {
        budget_exceeded_ = true;
        emit displayInfo(
            tr("Viewport display exceeds the %1-point budget (%2 shown; "
               "capacity warning, data is not dropped)")
                .arg(kViewportPointBudget)
                .arg(total));
    } else if (total <= kViewportPointBudget) {
        budget_exceeded_ = false;
    }
#endif
}

}  // namespace app
