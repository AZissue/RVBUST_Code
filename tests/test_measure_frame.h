#pragma once

#include <QObject>

// 阶段 27：测量帧（src/logic/MeasureFrame.{h,cpp}）的落盘与读回。
//
// 这不是"再存一份数据"的装饰功能：3.0 规划 M-02 要求真件可回放，并且
// measure_truth 的 .grid 格式就是这里的 frame.grid —— 现场抓到的一帧
// 必须能被同一套读取链路原样读回，否则"改算法前先有标尺"就是一句空话。
class TestMeasureFrame : public QObject {
    Q_OBJECT
private slots:
    // 往返：网格（含 NaN）、图像、ROI、结果行、主值与 extra 全部原样回来。
    void roundTripKeepsEverything();
    // 空网格 / 尺寸与点数不符必须拒绝，不能写出一个半截的帧。
    void saveRejectsGridSizeMismatch();
    // 清单里的尺寸与网格头不一致时拒绝（防止"清单说 720×540、数据是别的"）。
    void loadRejectsManifestGridMismatch();
    // 网格头非法 / 数据长度不符时拒绝，并给出可读原因。
    void loadRejectsBadGridHeader();
    // ROI 越出图像范围时拒绝：回放时不能把框套到错误的位置。
    void loadRejectsRoiOutsideImage();
    // 目录名只保留方法 id 的 ASCII 字符，并带时间戳。
    void suggestDirKeepsMethodIdAscii();
};
