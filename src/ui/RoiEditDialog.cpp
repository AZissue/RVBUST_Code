#include "RoiEditDialog.h"

#include <QComboBox>
#include <QDialogButtonBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QStackedWidget>
#include <QVBoxLayout>

#include "Roi2DView.h"
#include "Viewport3D.h"
#include "modules/CloudUtils.h"
#include "core/ModuleBase.h"

namespace rvc {

RoiEditDialog::RoiEditDialog(ModuleBase* module, PointCloud cloud, QWidget* parent)
    : QDialog(parent), module_(module), cloud_(std::move(cloud))
{
    setWindowTitle(QStringLiteral("设置 ROI"));
    setModal(true);
    resize(720, 640);

    auto* layout = new QVBoxLayout(this);

    // ---- 模式选择 ----
    auto* modeLayout = new QHBoxLayout;
    modeLayout->addWidget(new QLabel(QStringLiteral("ROI 类型："), this));
    modeCombo_ = new QComboBox(this);
    modeCombo_->addItem(QStringLiteral("3D 盒体"), false);
    modeCombo_->addItem(QStringLiteral("2D 矩形（XY 平面）"), true);
    modeLayout->addWidget(modeCombo_, 1);
    layout->addLayout(modeLayout);

    // ---- 预览视图 ----
    stack_ = new QStackedWidget(this);

    view3d_ = new Viewport3D(stack_);
    view3d_->setPointCloud(cloud_);
    view3d_->roiPickedCallback = [this](RoiBox roi) { onRoi3DPicked(roi); };
    stack_->addWidget(view3d_);

    view2d_ = new Roi2DView(stack_);
    view2d_->setPointCloud(cloud_);
    connect(view2d_, &Roi2DView::roiChanged, this, &RoiEditDialog::onRoi2DChanged);
    stack_->addWidget(view2d_);

    layout->addWidget(stack_, 1);

    // ---- 参数编辑 ----
    auto* paramGroup = new QGroupBox(QStringLiteral("ROI 范围（米）"), this);
    auto* form = new QFormLayout(paramGroup);

    auto makeSpin = [this]() {
        auto* spin = new QDoubleSpinBox(this);
        spin->setRange(-1e9, 1e9);
        spin->setDecimals(6);
        spin->setSingleStep(0.001);
        connect(spin, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this,
                &RoiEditDialog::onSpinEdited);
        return spin;
    };

    spinXmin_ = makeSpin();
    spinXmax_ = makeSpin();
    spinYmin_ = makeSpin();
    spinYmax_ = makeSpin();
    spinZmin_ = makeSpin();
    spinZmax_ = makeSpin();

    form->addRow(QStringLiteral("X min"), spinXmin_);
    form->addRow(QStringLiteral("X max"), spinXmax_);
    form->addRow(QStringLiteral("Y min"), spinYmin_);
    form->addRow(QStringLiteral("Y max"), spinYmax_);
    form->addRow(QStringLiteral("Z min"), spinZmin_);
    form->addRow(QStringLiteral("Z max"), spinZmax_);

    layout->addWidget(paramGroup);

    // ---- 按钮 ----
    buttons_ = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel, this);
    connect(buttons_, &QDialogButtonBox::accepted, this, &RoiEditDialog::accept);
    connect(buttons_, &QDialogButtonBox::rejected, this, &QDialog::reject);
    layout->addWidget(buttons_);

    connect(modeCombo_, QOverload<int>::of(&QComboBox::currentIndexChanged), this,
            &RoiEditDialog::onModeChanged);

    syncFromModule();
    syncToViews();
    onModeChanged(modeCombo_->currentIndex());
}

RoiBox RoiEditDialog::roi() const
{
    return currentRoi_;
}

void RoiEditDialog::syncFromModule()
{
    currentRoi_ = readRoiFromParams(*module_);
    if (!currentRoi_.valid) {
        // 默认：3D 模式，覆盖整个点云
        currentRoi_ = RoiBox::fromMinMax({-1e9f, -1e9f, -1e9f}, {1e9f, 1e9f, 1e9f}, false);
    }
    modeCombo_->setCurrentIndex(currentRoi_.is2D ? 1 : 0);
}

void RoiEditDialog::syncToViews()
{
    spinXmin_->setValue(currentRoi_.min.x());
    spinXmax_->setValue(currentRoi_.max.x());
    spinYmin_->setValue(currentRoi_.min.y());
    spinYmax_->setValue(currentRoi_.max.y());
    spinZmin_->setValue(currentRoi_.min.z());
    spinZmax_->setValue(currentRoi_.max.z());

    view2d_->setRoi(currentRoi_);
    view3d_->setRoi(currentRoi_);
}

void RoiEditDialog::onModeChanged(int index)
{
    currentRoi_.is2D = modeCombo_->itemData(index).toBool();
    if (currentRoi_.is2D) {
        currentRoi_.min.z() = -1e9f;
        currentRoi_.max.z() = 1e9f;
    }
    updateSpinVisibility();
    stack_->setCurrentIndex(index);
    // 3D 模式开启 ROI 编辑，2D 模式关闭
    view3d_->setRoiEditing(!currentRoi_.is2D);
    syncToViews();
}

void RoiEditDialog::updateSpinVisibility()
{
    const bool is2D = currentRoi_.is2D;
    spinZmin_->setEnabled(!is2D);
    spinZmax_->setEnabled(!is2D);
    if (is2D) {
        spinZmin_->setValue(-1e9);
        spinZmax_->setValue(1e9);
    }
}

void RoiEditDialog::onRoi2DChanged(const RoiBox& roi)
{
    currentRoi_ = roi;
    currentRoi_.is2D = true;
    syncToViews();
}

void RoiEditDialog::onRoi3DPicked(const RoiBox& roi)
{
    currentRoi_ = roi;
    currentRoi_.is2D = false;
    syncToViews();
}

void RoiEditDialog::onSpinEdited()
{
    currentRoi_.min = Eigen::Vector3f(static_cast<float>(spinXmin_->value()),
                                      static_cast<float>(spinYmin_->value()),
                                      static_cast<float>(spinZmin_->value()));
    currentRoi_.max = Eigen::Vector3f(static_cast<float>(spinXmax_->value()),
                                      static_cast<float>(spinYmax_->value()),
                                      static_cast<float>(spinZmax_->value()));
    currentRoi_.valid = true;
    currentRoi_.is2D = modeCombo_->currentData().toBool();
    view2d_->setRoi(currentRoi_);
    view3d_->setRoi(currentRoi_);
}

void RoiEditDialog::accept()
{
    currentRoi_.valid = true;
    if (module_) {
        writeRoiToParams(*module_, currentRoi_);
    }
    QDialog::accept();
}

} // namespace rvc
