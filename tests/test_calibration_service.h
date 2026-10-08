#pragma once

#include <QObject>

class TestCalibrationService : public QObject {
    Q_OBJECT
private slots:
    void normalizePoseLineAcceptsSpacesAndCommas();
    void normalizePoseLineRejectsBadInput();
    void errorTextMapping();
    // T-008：SDK 内部异常（桥接层拦截到的 SEH/异常）不能再被说成"参数无效"。
    void sdkInternalErrorIsDistinctFromBadParameters();
    // T-008 r2：标定结果的正文格式化收敛成一个纯函数（两个界面页共用）。
    void formatResultCarriesMatrixAndPerFrameErrors();

    // ── 戳点标定（TCP touch）──
    // 返回码表不能和标定板共用：同为 -2，标定板是"有效数据不足 6 组"，
    // 戳点是"相机点位数据无效"。
    void tcpErrorTextMapping();
    void normalizeXyzLineAcceptsSpacesAndCommas();
    // 进 SDK 之前先把"哪一列哪一组缺了"说清楚。
    void tcpTouchValidatesColumnsBeforeSdk();
    // 眼在手上才需要机器人拍照位姿；眼在手外传空串（桥接层翻成 nullptr）。
    void tcpTouchRequiresPoseOnlyForEyeInHand();
    // 入口必须按 calibType 分派 —— 用户报告的"第 1 组机器人拍照位姿格式无效"
    // 就是"戳点标定被送到了标定板接口"的症状。
    void calibrateDispatchesOnCalibType();
};
