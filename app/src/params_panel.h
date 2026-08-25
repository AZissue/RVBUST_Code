#pragma once

#include "pcsearch/pipeline/node.h"

#include <QWidget>

class QFormLayout;

namespace app {

class ParamsPanel : public QWidget {
    Q_OBJECT
public:
    explicit ParamsPanel(QWidget* parent = nullptr);
    void showNode(pcsearch::pipeline::Node* node);
    void clearPanel();
    void setChinese(bool zh);

signals:
    void paramChanged(const QString& nodeId, const QString& name,
                      pcsearch::pipeline::ParamValue value);
    // Node-specific toolbar actions, e.g. box_roi -> "fit_bounds".
    void actionRequested(const QString& nodeId, const QString& action);

private:
    QFormLayout* form_ = nullptr;
    pcsearch::pipeline::Node* node_ = nullptr;
    QWidget* container_ = nullptr;
    bool chinese_ = true;
};

}  // namespace app
