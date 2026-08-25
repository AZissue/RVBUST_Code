#include "simple_translator.h"

namespace app {

SimpleTranslator::SimpleTranslator() {
    map_[QStringLiteral("&File")] = QStringLiteral("文件(&F)");
    map_[QStringLiteral("&Edit")] = QStringLiteral("编辑(&E)");
    map_[QStringLiteral("&View")] = QStringLiteral("视图(&V)");
    map_[QStringLiteral("&Help")] = QStringLiteral("帮助(&H)");
    map_[QStringLiteral("Open Cloud...")] = QStringLiteral("打开点云...");
    map_[QStringLiteral("Save Solution...")] = QStringLiteral("保存方案...");
    map_[QStringLiteral("Open Solution...")] = QStringLiteral("打开方案...");
    map_[QStringLiteral("&Run Graph")] = QStringLiteral("运行流程(&R)");
    map_[QStringLiteral("Run Graph")] = QStringLiteral("运行流程");
    map_[QStringLiteral("Exit")] = QStringLiteral("退出");
    map_[QStringLiteral("Theme")] = QStringLiteral("主题");
    map_[QStringLiteral("Light")] = QStringLiteral("浅色");
    map_[QStringLiteral("Dark")] = QStringLiteral("深色");
    map_[QStringLiteral("Language")] = QStringLiteral("语言");
    map_[QStringLiteral("中文")] = QStringLiteral("中文");
    map_[QStringLiteral("English")] = QStringLiteral("English");
    map_[QStringLiteral("About")] = QStringLiteral("关于");
    map_[QStringLiteral("Node Library")] = QStringLiteral("节点库");
    map_[QStringLiteral("Flow Graph")] = QStringLiteral("流程编辑");
    map_[QStringLiteral("Components")] = QStringLiteral("功能组件");
    map_[QStringLiteral("Canvas")] = QStringLiteral("画布");
    map_[QStringLiteral("Cloud Properties")] = QStringLiteral("点云属性");
    map_[QStringLiteral("Parameters")] = QStringLiteral("参数");
    map_[QStringLiteral("Log")] = QStringLiteral("操作日志");
    map_[QStringLiteral("Connections")] = QStringLiteral("连接");
    map_[QStringLiteral("Results")] = QStringLiteral("结果");
    map_[QStringLiteral("Show Output:")] = QStringLiteral("显示输出:");
    map_[QStringLiteral("Run")] = QStringLiteral("运行");
    map_[QStringLiteral("ROI")] = QStringLiteral("框选");
    map_[QStringLiteral("Search nodes...")] = QStringLiteral("搜索节点...");
    map_[QStringLiteral("Select a node")] = QStringLiteral("选择一个节点");
    map_[QStringLiteral("3D View")] = QStringLiteral("3D 视图");
    map_[QStringLiteral("Log")] = QStringLiteral("日志");
    map_[QStringLiteral("Drag nodes here, connect ports, press F5 to run.")] =
        QStringLiteral("拖入节点，连接端口，按 F5 运行。");
    map_[QStringLiteral("Graph executed successfully")] =
        QStringLiteral("流程执行成功");
    map_[QStringLiteral("Graph is already running")] =
        QStringLiteral("流程正在运行");
    map_[QStringLiteral("Graph is running; editing disabled")] =
        QStringLiteral("流程运行中，禁止编辑");
    map_[QStringLiteral("Nothing to run - add nodes first")] =
        QStringLiteral("流程为空，请先添加节点");
    map_[QStringLiteral("Running graph...")] =
        QStringLiteral("正在运行流程...");
    map_[QStringLiteral("Graph execution failed")] =
        QStringLiteral("流程执行失败");
    map_[QStringLiteral("Connection failed")] = QStringLiteral("连接失败");
    map_[QStringLiteral("Node %1: %2 ms")] = QStringLiteral("节点 %1: %2 毫秒");
    map_[QStringLiteral("Added node: %1")] = QStringLiteral("已添加节点: %1");
    map_[QStringLiteral("Connected %1 -> %2")] = QStringLiteral("已连接 %1 -> %2");
    map_[QStringLiteral("Solution saved: %1")] = QStringLiteral("方案已保存: %1");
    map_[QStringLiteral("Solution loaded: %1")] = QStringLiteral("方案已加载: %1");
    map_[QStringLiteral("Cannot write solution file")] =
        QStringLiteral("无法写入方案文件");
    map_[QStringLiteral("Cannot open solution file")] =
        QStringLiteral("无法打开方案文件");
    map_[QStringLiteral("Add 3D Viewport")] = QStringLiteral("添加 3D 视窗");
    map_[QStringLiteral("Displayed %1 in viewport %2")] =
        QStringLiteral("已在视窗 %2 显示 %1");
    map_[QStringLiteral("Canvas Background")] = QStringLiteral("画布背景");
    map_[QStringLiteral("Grid")] = QStringLiteral("网格");
    map_[QStringLiteral("Dots")] = QStringLiteral("点阵");
    map_[QStringLiteral("Solid")] = QStringLiteral("纯色");
    map_[QStringLiteral("Custom Image...")] = QStringLiteral("自定义图片...");
    map_[QStringLiteral("Load Canvas Background")] = QStringLiteral("加载画布背景");
    map_[QStringLiteral("Delete Node")] = QStringLiteral("删除节点");
    map_[QStringLiteral("Deleted node: %1")] = QStringLiteral("已删除节点: %1");
    map_[QStringLiteral("Disconnect")] = QStringLiteral("断开连接");
    map_[QStringLiteral("Disconnected %1 -> %2")] = QStringLiteral("已断开 %1 -> %2");
    map_[QStringLiteral("Select Point Cloud")] = QStringLiteral("选择点云文件");
    map_[QStringLiteral("Select Output Path")] = QStringLiteral("选择输出路径");
    map_[QStringLiteral("Point Clouds (*.pcd *.ply *.xyz *.csv *.txt);;All Files (*)")] =
        QStringLiteral("点云文件 (*.pcd *.ply *.xyz *.csv *.txt);;所有文件 (*)");
    map_[QStringLiteral("Release over an input port to connect")] =
        QStringLiteral("在输入端口上松开以连线");
    map_[QStringLiteral("Cannot load canvas background image")] =
        QStringLiteral("无法加载画布背景图片");
    map_[QStringLiteral("Select a Box ROI node first, then press ROI")] =
        QStringLiteral("请先选中 Box ROI 节点，再点框选");
    map_[QStringLiteral("Drag the ROI box; its extents will be written to the selected Box ROI node")] =
        QStringLiteral("拖动 ROI 框，范围将写回选中的 Box ROI 节点");
    map_[QStringLiteral("ROI edit enabled: left-drag the body to move, drag corner handles to scale, drag edge handles to rotate; wheel zooms; results are written back to the Box ROI node")] =
        QStringLiteral("ROI 框选已开启：左键拖盒体移动、拖角手柄缩放、拖边手柄旋转，滚轮缩放视窗；结果写回 Box ROI 节点");
    map_[QStringLiteral("ROI updated: center(%1, %2, %3) half(%4, %5, %6) rotation(%7, %8, %9) deg (press F5 to recompute)")] =
        QStringLiteral("ROI 框选更新：中心(%1, %2, %3) 半长(%4, %5, %6) 旋转(%7, %8, %9)°（按 F5 重新计算）");
    map_[QStringLiteral("Reset bounds failed: Box ROI has no input point cloud")] =
        QStringLiteral("重置包围盒失败：Box ROI 没有可用的输入点云");
    map_[QStringLiteral("Reset bounds failed: Box ROI has no input point cloud (connect Load Cloud -> Box ROI and run first)")] =
        QStringLiteral("重置包围盒失败：Box ROI 没有可用的输入点云（请先连接 点云加载 → Box ROI 并运行）");
    map_[QStringLiteral("Reset bounds failed: Box ROI received no point cloud (connect Load Cloud -> Box ROI and run the graph first)")] =
        QStringLiteral("重置包围盒失败：Box ROI 未接收到点云（请先连接 点云加载 → Box ROI 并运行流程）");
    map_[QStringLiteral("Reset bounds failed: input cloud has no valid points (all NaN/Inf); add Remove Invalid Points before Box ROI")] =
        QStringLiteral("重置包围盒失败：输入点云没有有效点（全是 NaN/Inf），请在 Box ROI 前接入「移除无效点」");
    map_[QStringLiteral("Reset bounds failed: %1")] =
        QStringLiteral("重置包围盒失败：%1");
    map_[QStringLiteral("Reset bounds to input cloud: x[%1, %2] y[%3, %4] z[%5, %6] (press F5 to recompute)")] =
        QStringLiteral("已按输入点云重置包围盒：x[%1, %2] y[%3, %4] z[%5, %6]（按 F5 重新计算）");
    map_[QStringLiteral("Reset bounds to input cloud (%1 valid points): x[%2, %3] y[%4, %5] z[%6, %7] (press F5 to recompute)")] =
        QStringLiteral("已按输入点云重置包围盒（有效点 %1）：x[%2, %3] y[%4, %5] z[%6, %7]（按 F5 重新计算）");
    map_[QStringLiteral("No parameters")] = QStringLiteral("无参数");
}

QString SimpleTranslator::translate(const char*, const char* sourceText, const char*, int) const {
    if (!sourceText) return QString();
    const auto it = map_.find(QString::fromUtf8(sourceText));
    return it == map_.end() ? QString() : *it;
}

}  // namespace app
