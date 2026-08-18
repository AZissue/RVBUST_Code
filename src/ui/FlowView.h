#pragma once

// 流程画布视图：QtNodes GraphicsView 子类，增加工具箱拖放支持。

#include <QtNodes/GraphicsView>

namespace rvc {

class FlowModel;

class FlowView : public QtNodes::GraphicsView {
    Q_OBJECT
public:
    explicit FlowView(FlowModel& model, QtNodes::BasicGraphicsScene* scene,
                      QWidget* parent = nullptr);

protected:
    void dragEnterEvent(QDragEnterEvent* event) override;
    void dragMoveEvent(QDragMoveEvent* event) override;
    void dropEvent(QDropEvent* event) override;

private:
    FlowModel& model_;
};

} // namespace rvc
