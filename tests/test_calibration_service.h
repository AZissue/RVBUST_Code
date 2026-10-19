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

    // ── 位姿格式（卡片里 3 个旋转数该怎么读）──
    // 欧拉 RPY 必须与 normalizePoseLine 逐字节相同：既有机器人（FANUC 等）
    // 走的就是这条路，改格式功能不能动到它们已核定的结果。
    void eulerRpyStaysOnTheOldPoseTypeZeroPath();
    // UR 的轴角旋转矢量：卡片 3 个数不能当欧拉读，必须转成 16 数矩阵（poseType=3）。
    void rotationVectorBecomesMatrix16();
    // 四种 3 数格式 x 度/弧度：输出的 3x3 必须等于 RobotDataFormats 的同一转换。
    void everyThreeValueFormatMatchesCatalog();
    // 界面提示要说清楚交给 SDK 的 poseType：sXYZ=0、其它 3 数约定=3、
    // 卡片装不下的格式=-1（不会发送）。
    void sdkPoseTypeMatchesTheCalibrationPath();
    // 卡片只有 6 个数：四元数(4)/9 数矩阵在这里无法表示，应拒绝而不是抛异常。
    void formatsTheCardCannotCarryAreRejected();
    void toSdkPoseLineRejectsBadInput();
    // 格式名要给界面和日志用：7 个都得有、且互不相同。
    void poseFormatNamesAreDistinctAndComplete();
};
