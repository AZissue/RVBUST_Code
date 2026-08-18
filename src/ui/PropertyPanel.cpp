#include "PropertyPanel.h"

#include <QCheckBox>
#include <QDoubleSpinBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QSpinBox>
#include <QVBoxLayout>

#include "RoiEditDialog.h"

namespace rvc {

PropertyPanel::PropertyPanel(QWidget* mainWindow, QWidget* parent)
    : QWidget(parent), mainWindow_(mainWindow)
{
    auto* layout = new QVBoxLayout(this);
    titleLabel_ = new QLabel(QStringLiteral("未选中节点"), this);
    QFont f = titleLabel_->font();
    f.setBold(true);
    titleLabel_->setFont(f);
    layout->addWidget(titleLabel_);

    formHolder_ = new QWidget(this);
    formLayout_ = new QFormLayout(formHolder_);
    formLayout_->setContentsMargins(0, 0, 0, 0);
    layout->addWidget(formHolder_);
    layout->addStretch();
}

void PropertyPanel::setModule(ModuleBase* module)
{
    module_ = module;
    rebuild();
}

bool PropertyPanel::hasRoiParams() const
{
    if (!module_)
        return false;
    for (const auto& desc : module_->paramDescs()) {
        if (desc.name == "roiEnabled")
            return true;
    }
    return false;
}

void PropertyPanel::rebuild()
{
    // 清空旧控件
    while (QLayoutItem* item = formLayout_->takeAt(0)) {
        if (QWidget* w = item->widget())
            delete w;
        delete item;
    }
    roiButton_ = nullptr;

    if (!module_) {
        titleLabel_->setText(QStringLiteral("未选中节点"));
        return;
    }

    titleLabel_->setText(QString::fromStdString(module_->name()));

    const auto& descs = module_->paramDescs();
    if (descs.empty()) {
        formLayout_->addRow(new QLabel(QStringLiteral("（无参数）"), formHolder_));
        return;
    }

    for (const ParamDesc& desc : descs) {
        formLayout_->addRow(QString::fromStdString(desc.name), buildEditor(desc));
    }

    // ROI 设置按钮：模块带 roiEnabled 参数组时显示
    if (hasRoiParams()) {
        roiButton_ = new QPushButton(QStringLiteral("设置 ROI…"), formHolder_);
        connect(roiButton_, &QPushButton::clicked, this, &PropertyPanel::openRoiDialog);
        formLayout_->addRow(QStringLiteral("ROI"), roiButton_);
    }
}

void PropertyPanel::openRoiDialog()
{
    if (!module_)
        return;

    PointCloud cloud;
    if (currentCloudProvider)
        cloud = currentCloudProvider();

    if (!cloud || cloud->empty()) {
        QMessageBox::information(mainWindow_, QStringLiteral("设置 ROI"),
                                 QStringLiteral("请先运行流程让视窗加载点云，再设置 ROI。"));
        return;
    }

    RoiEditDialog dlg(module_, cloud, mainWindow_);
    if (dlg.exec() == QDialog::Accepted) {
        // 参数已写回模块，刷新面板显示
        setModule(module_);
    }
}

QWidget* PropertyPanel::buildEditor(const ParamDesc& desc)
{
    ModuleBase* module = module_;
    const std::string name = desc.name;

    switch (desc.type) {
    case ParamType::Double: {
        auto* spin = new QDoubleSpinBox(formHolder_);
        spin->setRange(desc.minValue, desc.maxValue);
        spin->setDecimals(6);
        spin->setSingleStep(0.001);
        spin->setValue(module->getDouble(name));
        connect(spin, QOverload<double>::of(&QDoubleSpinBox::valueChanged), spin,
                [module, name](double v) { module->setParam(name, v); });
        return spin;
    }
    case ParamType::Int: {
        auto* spin = new QSpinBox(formHolder_);
        spin->setRange(static_cast<int>(desc.minValue), static_cast<int>(desc.maxValue));
        spin->setValue(module->getInt(name));
        connect(spin, QOverload<int>::of(&QSpinBox::valueChanged), spin,
                [module, name](int v) { module->setParam(name, v); });
        return spin;
    }
    case ParamType::Bool: {
        auto* check = new QCheckBox(formHolder_);
        check->setChecked(module->getBool(name));
        connect(check, &QCheckBox::toggled, check,
                [module, name](bool v) { module->setParam(name, v); });
        return check;
    }
    case ParamType::String: {
        auto* edit = new QLineEdit(QString::fromStdString(module->getString(name)), formHolder_);
        connect(edit, &QLineEdit::editingFinished, edit,
                [module, name, edit] { module->setParam(name, edit->text().toStdString()); });
        return edit;
    }
    case ParamType::FilePath: {
        auto* holder = new QWidget(formHolder_);
        auto* h = new QHBoxLayout(holder);
        h->setContentsMargins(0, 0, 0, 0);
        auto* edit = new QLineEdit(QString::fromStdString(module->getString(name)), holder);
        auto* browse = new QPushButton(QStringLiteral("…"), holder);
        browse->setMaximumWidth(28);
        h->addWidget(edit);
        h->addWidget(browse);
        connect(edit, &QLineEdit::editingFinished, edit,
                [module, name, edit] { module->setParam(name, edit->text().toStdString()); });
        connect(browse, &QPushButton::clicked, holder, [this, module, name, edit] {
            const QString path = QFileDialog::getOpenFileName(
                mainWindow_, QStringLiteral("选择文件"), QString(),
                QStringLiteral("PLY 文件 (*.ply);;所有文件 (*)"));
            if (!path.isEmpty()) {
                edit->setText(path);
                module->setParam(name, path.toStdString());
            }
        });
        return holder;
    }
    }
    return new QLabel(QStringLiteral("?"), formHolder_);
}

} // namespace rvc
