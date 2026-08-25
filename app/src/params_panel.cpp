#include "params_panel.h"

#include "node_titles.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QToolButton>
#include <QVBoxLayout>

namespace app {

namespace {

// Type-safe variant -> QString. A wrong variant alternative (e.g. a File
// param holding a double) must never throw when the editor is built.
QString valueText(const pcsearch::pipeline::ParamValue& v) {
    if (const auto* s = std::get_if<std::string>(&v)) return QString::fromStdString(*s);
    if (const auto* d = std::get_if<double>(&v)) return QString::number(*d);
    if (const auto* i = std::get_if<int>(&v)) return QString::number(*i);
    if (const auto* b = std::get_if<bool>(&v)) return *b ? QStringLiteral("true")
                                                         : QStringLiteral("false");
    return {};
}

}  // namespace

ParamsPanel::ParamsPanel(QWidget* parent) : QWidget(parent) {
    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(0, 0, 0, 0);
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    container_ = new QWidget;
    form_ = new QFormLayout(container_);
    scroll->setWidget(container_);
    root->addWidget(scroll);
}

void ParamsPanel::clearPanel() {
    node_ = nullptr;
    while (form_->rowCount() > 0) form_->removeRow(0);
}

void ParamsPanel::setChinese(bool zh) {
    chinese_ = zh;
    showNode(node_);
}

void ParamsPanel::showNode(pcsearch::pipeline::Node* node) {
    clearPanel();
    if (!node) return;
    node_ = node;
    const auto& params = node->params();
    for (const auto& def : params.defs()) {
        const QString label =
            paramLabel(def.label, chinese_) +
            (def.unit.empty() ? QString() : QString(" (%1)").arg(QString::fromStdString(def.unit)));
        QWidget* editor = nullptr;
        const auto& value = params.values().at(def.name);
        switch (def.type) {
            case pcsearch::pipeline::ParamType::Double: {
                auto* spin = new QDoubleSpinBox(container_);
                spin->setRange(def.dmin, def.dmax);
                spin->setDecimals(4);
                spin->setValue(std::get_if<double>(&value) ? std::get<double>(value)
                                                           : def.dmin);
                connect(spin, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this,
                        [this, name = QString::fromStdString(def.name)](double v) {
                            emit paramChanged(node_ ? QString::fromStdString(node_->id()) : QString(),
                                              name, pcsearch::pipeline::ParamValue{v});
                        });
                editor = spin;
                break;
            }
            case pcsearch::pipeline::ParamType::Int: {
                auto* spin = new QSpinBox(container_);
                spin->setRange(def.imin, def.imax);
                spin->setValue(std::get_if<int>(&value) ? std::get<int>(value)
                                                        : def.imin);
                connect(spin, QOverload<int>::of(&QSpinBox::valueChanged), this,
                        [this, name = QString::fromStdString(def.name)](int v) {
                            emit paramChanged(node_ ? QString::fromStdString(node_->id()) : QString(),
                                              name, pcsearch::pipeline::ParamValue{v});
                        });
                editor = spin;
                break;
            }
            case pcsearch::pipeline::ParamType::Bool: {
                auto* cb = new QCheckBox(container_);
                cb->setChecked(std::get_if<bool>(&value) ? std::get<bool>(value)
                                                         : false);
                connect(cb, &QCheckBox::toggled, this,
                        [this, name = QString::fromStdString(def.name)](bool v) {
                            emit paramChanged(node_ ? QString::fromStdString(node_->id()) : QString(),
                                              name, pcsearch::pipeline::ParamValue{v});
                        });
                editor = cb;
                break;
            }
            case pcsearch::pipeline::ParamType::String: {
                auto* edit = new QLineEdit(valueText(value), container_);
                connect(edit, &QLineEdit::editingFinished, this,
                        [this, edit, name = QString::fromStdString(def.name)]() {
                            emit paramChanged(node_ ? QString::fromStdString(node_->id()) : QString(),
                                              name,
                                              pcsearch::pipeline::ParamValue{edit->text().toStdString()});
                        });
                editor = edit;
                break;
            }
            case pcsearch::pipeline::ParamType::File: {
                auto* holder = new QWidget(container_);
                auto* h = new QHBoxLayout(holder);
                h->setContentsMargins(0, 0, 0, 0);
                auto* edit = new QLineEdit(valueText(value), holder);
                auto* browse = new QToolButton(holder);
                browse->setText(tr("..."));
                browse->setAutoRaise(true);
                h->addWidget(edit, 1);
                h->addWidget(browse);
                connect(edit, &QLineEdit::editingFinished, this,
                        [this, edit, name = QString::fromStdString(def.name)]() {
                            emit paramChanged(
                                node_ ? QString::fromStdString(node_->id()) : QString(),
                                name,
                                pcsearch::pipeline::ParamValue{edit->text().toStdString()});
                        });
                connect(browse, &QToolButton::clicked, this,
                        [this, edit, name = QString::fromStdString(def.name)]() {
                            const bool is_save = node_ && node_->type() == "save_cloud";
                            const QString filter =
                                tr("Point Clouds (*.pcd *.ply *.xyz *.csv *.txt);;All Files (*)");
                            const QString path = is_save
                                                     ? QFileDialog::getSaveFileName(
                                                           this, tr("Select Output Path"), {},
                                                           filter)
                                                     : QFileDialog::getOpenFileName(
                                                           this, tr("Select Point Cloud"), {},
                                                           filter);
                            if (path.isEmpty()) return;
                            edit->setText(path);
                            emit paramChanged(
                                node_ ? QString::fromStdString(node_->id()) : QString(),
                                name, pcsearch::pipeline::ParamValue{path.toStdString()});
                        });
                editor = holder;
                break;
            }
            case pcsearch::pipeline::ParamType::Directory: {
                auto* holder = new QWidget(container_);
                auto* h = new QHBoxLayout(holder);
                h->setContentsMargins(0, 0, 0, 0);
                auto* edit = new QLineEdit(valueText(value), holder);
                auto* browse = new QToolButton(holder);
                browse->setText(tr("..."));
                browse->setAutoRaise(true);
                h->addWidget(edit, 1);
                h->addWidget(browse);
                connect(edit, &QLineEdit::editingFinished, this,
                        [this, edit, name = QString::fromStdString(def.name)]() {
                            emit paramChanged(
                                node_ ? QString::fromStdString(node_->id()) : QString(),
                                name,
                                pcsearch::pipeline::ParamValue{edit->text().toStdString()});
                        });
                connect(browse, &QToolButton::clicked, this,
                        [this, edit, name = QString::fromStdString(def.name)]() {
                            const QString dir = QFileDialog::getExistingDirectory(
                                this, tr("Select Output Folder"), edit->text());
                            if (dir.isEmpty()) return;
                            edit->setText(dir);
                            emit paramChanged(
                                node_ ? QString::fromStdString(node_->id()) : QString(),
                                name, pcsearch::pipeline::ParamValue{dir.toStdString()});
                        });
                editor = holder;
                break;
            }
            case pcsearch::pipeline::ParamType::Enum: {
                auto* combo = new QComboBox(container_);
                for (const auto& e : def.enum_values) {
                    combo->addItem(QString::fromStdString(e));
                }
                combo->setCurrentText(valueText(value));
                connect(combo, &QComboBox::currentTextChanged, this,
                        [this, name = QString::fromStdString(def.name)](const QString& v) {
                            emit paramChanged(node_ ? QString::fromStdString(node_->id()) : QString(),
                                              name, pcsearch::pipeline::ParamValue{v.toStdString()});
                        });
                editor = combo;
                break;
            }
        }
        if (editor) {
            form_->addRow(label, editor);
        }
    }
    if (form_->rowCount() == 0) {
        form_->addRow(new QLabel(tr("No parameters"), container_));
    }
    // Node-specific actions: Box ROI gets a one-click fit-to-input-cloud
    // button that recomputes the whole bounding box and updates the params.
    if (node->type() == "box_roi") {
        auto* fit = new QPushButton(
            chinese_ ? tr("重置包围盒（按输入点云）")
                     : QStringLiteral("Reset Bounds (Fit Input Cloud)"),
            container_);
        const std::string node_id = node->id();
        connect(fit, &QPushButton::clicked, this,
                [this, node_id](bool) { emit actionRequested(
                    QString::fromStdString(node_id), QLatin1String("fit_bounds")); });
        form_->addRow(QString(), fit);
    }
}

}  // namespace app
