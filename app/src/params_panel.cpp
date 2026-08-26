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

#include <vector>

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
    struct EditorEntry {
        pcsearch::pipeline::ParamDef def;
        QWidget* editor = nullptr;
    };
    std::vector<EditorEntry> entries;
    for (const auto& def : params.defs()) {
        const QString label =
            paramLabel(def.label, chinese_) +
            (def.unit.empty() ? QString() : QString(" (%1)").arg(QString::fromStdString(def.unit)));
        QWidget* editor = nullptr;
        const auto& value = params.values().at(def.name);
        switch (def.type) {
            case pcsearch::pipeline::ParamType::Double: {
                auto* spin = new QDoubleSpinBox(container_);
                spin->setObjectName(QString::fromStdString(def.name));
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
                spin->setObjectName(QString::fromStdString(def.name));
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
                cb->setObjectName(QString::fromStdString(def.name));
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
                edit->setObjectName(QString::fromStdString(def.name));
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
                edit->setObjectName(QString::fromStdString(def.name));
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
                edit->setObjectName(QString::fromStdString(def.name));
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
                combo->setObjectName(QString::fromStdString(def.name));
                for (const auto& e : def.enum_values) {
                    combo->addItem(enumValueLabel(e, chinese_),
                                   QString::fromStdString(e));
                }
                const int cur = combo->findData(valueText(value));
                combo->setCurrentIndex(cur >= 0 ? cur : 0);
                connect(combo, QOverload<int>::of(&QComboBox::currentIndexChanged), this,
                        [this, combo, name = QString::fromStdString(def.name)](int idx) {
                            if (idx < 0 || idx >= combo->count()) return;
                            const QString raw = combo->itemData(idx).toString();
                            emit paramChanged(
                                node_ ? QString::fromStdString(node_->id()) : QString(),
                                name, pcsearch::pipeline::ParamValue{raw.toStdString()});
                        });
                editor = combo;
                break;
            }
        }
        if (editor) {
            // File/Directory editors are holder widgets wrapping a QLineEdit;
            // the inner control already carries the param name. Naming the
            // holder as well would shadow it in dependency findChild lookups
            // and the dependency value could never be read.
            if (def.type != pcsearch::pipeline::ParamType::File &&
                def.type != pcsearch::pipeline::ParamType::Directory) {
                editor->setObjectName(QString::fromStdString(def.name));
            }
            form_->addRow(label, editor);
            entries.push_back({def, editor});
        }
    }
    if (form_->rowCount() == 0) {
        form_->addRow(new QLabel(tr("No parameters"), container_));
    }

    // Parameter dependency: editors whose def.enable_when_param is set stay
    // disabled unless the referenced parameter holds enable_when_value
    // (e.g. Chunk Size editable only when Read Mode == chunked).
    // `entries` is a local of showNode(); the lambda outlives it (connected to
    // editor signals), so capture a copy, not a reference.
    const auto refreshEnabled = [this, entries]() {
        for (const auto& e : entries) {
            if (e.def.enable_when_param.empty()) continue;
            QWidget* dep = container_->findChild<QWidget*>(
                QString::fromStdString(e.def.enable_when_param));
            QString dep_value;
            if (auto* cb = qobject_cast<QComboBox*>(dep)) {
                dep_value = cb->currentData().toString();
            } else if (auto* le = qobject_cast<QLineEdit*>(dep)) {
                dep_value = le->text();
            } else if (auto* dsp = qobject_cast<QDoubleSpinBox*>(dep)) {
                dep_value = QString::number(dsp->value());
            } else if (auto* sp = qobject_cast<QSpinBox*>(dep)) {
                dep_value = QString::number(sp->value());
            } else if (auto* chk = qobject_cast<QCheckBox*>(dep)) {
                dep_value = chk->isChecked() ? QStringLiteral("true")
                                             : QStringLiteral("false");
            }
            e.editor->setEnabled(
                dep_value == QString::fromStdString(e.def.enable_when_value));
        }
    };
    for (const auto& e : entries) {
        if (e.def.enable_when_param.empty()) continue;
        QWidget* dep = container_->findChild<QWidget*>(
            QString::fromStdString(e.def.enable_when_param));
        if (auto* cb = qobject_cast<QComboBox*>(dep)) {
            connect(cb, QOverload<int>::of(&QComboBox::currentIndexChanged), this,
                    [refreshEnabled](int) { refreshEnabled(); });
        } else if (auto* le = qobject_cast<QLineEdit*>(dep)) {
            connect(le, &QLineEdit::textChanged, this,
                    [refreshEnabled](const QString&) { refreshEnabled(); });
        } else if (auto* sp = qobject_cast<QSpinBox*>(dep)) {
            connect(sp, QOverload<int>::of(&QSpinBox::valueChanged), this,
                    [refreshEnabled](int) { refreshEnabled(); });
        } else if (auto* dsp = qobject_cast<QDoubleSpinBox*>(dep)) {
            connect(dsp, QOverload<double>::of(&QDoubleSpinBox::valueChanged), this,
                    [refreshEnabled](double) { refreshEnabled(); });
        } else if (auto* chk = qobject_cast<QCheckBox*>(dep)) {
            connect(chk, &QCheckBox::toggled, this,
                    [refreshEnabled](bool) { refreshEnabled(); });
        }
    }
    refreshEnabled();
}

}  // namespace app
