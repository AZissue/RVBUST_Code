#pragma once

// 参数面板（属性 Dock）：按模块 ParamDesc 声明自动生成编辑控件。
// 画布选中节点时显示该模块参数；编辑即写回模块（GUI 线程）。

#include <functional>

#include <QWidget>

#include "core/ModuleBase.h"

class QFormLayout;
class QLabel;
class QPushButton;

namespace rvc {

class PropertyPanel : public QWidget {
    Q_OBJECT
public:
    // mainWindow 作为文件对话框的父窗口（原生对话框必须有正确 HWND 父对象）
    explicit PropertyPanel(QWidget* mainWindow, QWidget* parent = nullptr);

    // 显示指定模块的参数；nullptr 清空面板
    void setModule(ModuleBase* module);

    // 由 MainWindow 注入：获取当前用于 ROI 预览的点云（通常取主视窗已显示点云）
    std::function<PointCloud()> currentCloudProvider;

private:
    void rebuild();
    QWidget* buildEditor(const ParamDesc& desc);
    bool hasRoiParams() const;
    void openRoiDialog();

    QWidget* mainWindow_;
    ModuleBase* module_ = nullptr;
    QLabel* titleLabel_;
    QWidget* formHolder_;
    QFormLayout* formLayout_;
    QPushButton* roiButton_ = nullptr;
};

} // namespace rvc
