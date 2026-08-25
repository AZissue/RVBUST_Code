#pragma once

#include "pcsearch/pipeline/registry.h"

#include <QWidget>

class QLineEdit;
class QTreeWidget;
class QTreeWidgetItem;

namespace app {

// Category tree of algorithm nodes with a filter box (Ctrl+F focuses it).
// Node entries support drag & drop onto the canvas and double-click
// instantiation.
class ToolboxWidget : public QWidget {
    Q_OBJECT
public:
    explicit ToolboxWidget(QWidget* parent = nullptr);

    void populate(const std::vector<pcsearch::pipeline::NodeInfo>& infos, bool zh);
    void setSearchPlaceholder(const QString& text);

public slots:
    void focusSearch();

signals:
    void nodeActivated(const QString& type);

private:
    void applyFilter(const QString& text);

    QLineEdit* search_ = nullptr;
    QTreeWidget* tree_ = nullptr;
};

}  // namespace app
