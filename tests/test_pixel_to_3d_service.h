#pragma once

#include <QObject>

// 第 11 回合任务 001（Codex 验收测试，不是实现方写的）：
// src/logic/PixelTo3DService.{h,cpp} 的行为契约。
//
// 这轮把「像素 → 3D 点」从 ToolsPanel 里抽成共享服务，供在线/离线共用。
// 抽取不许改行为，所以这里逐条钉住：分派顺序（对应图 > 对齐直查 > 投影）、
// 结果点与「直接组合 PixelTo3DTools 纯函数」逐位一致、失败状态的语义、
// 以及结果行的格式化。
class TestPixelTo3DService : public QObject {
    Q_OBJECT
private slots:
    void hasDataOnlyWhenUsable();
    void missingCloudIsNoData();
    void badImageSizeIsNoData();

    void alignedPixelMapsToItsOwnPoint();
    void alignedOutOfRangePixelIsOutOfRange();
    void alignedInvalidPointIsNoPointAtPixel();

    void nonAlignedWithoutIntrinsicsAsksForThem();
    void nonAlignedWithZeroFocalIsInvalid();
    void projectedPathMatchesTheOldComputation();

    void correspondMapBeatsAlignedLayout();
    void correspondMapOutOfRangePixel();

    void formatPointKeepsThreeDecimals();
    void statusTextIsReadableChinese();
};
