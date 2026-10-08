#pragma once
#include <QString>

enum class EyeHandMode { EyeToHand, EyeInHand };
enum class CalibType { Marker, TcpTouch };
enum class MarkerType { ConcentricCircle, AsymmetricGrid };

// ── 模式 → 数据列 的唯一判据 ──────────────────────────────────────────
//
// 「眼在手外 + 戳点」是唯一不需要机器人拍照位姿的组合：相机固定不动，机器人只
// 戳点，没有"拍照时的机器人位姿"这回事。凡是"这一列要不要填 / 要不要显示 /
// 要不要读 / 要不要参与质检"，都调这里 —— 别再手写一遍。
//
// 这条规则原先散在五处各写各的（保存校验、卡片显隐、文件预览、质检数据源、
// 读位姿按钮），2026-10-08 一天之内就有三处因为漏看它而出错：质检在空列上跑出
// 假"正常"、计算走错 SDK 通道、眼在手外+戳点时「拍照位姿」按钮没隐去。
inline bool needsCapturePose(EyeHandMode eyeHand, CalibType calibType)
{
    return !(eyeHand == EyeHandMode::EyeToHand && calibType == CalibType::TcpTouch);
}

// 机器人目标点（戳点）只有戳点标定要；标定板标定没有这一列。
inline bool needsRobotTarget(CalibType calibType)
{
    return calibType == CalibType::TcpTouch;
}

struct CalibrationMode {
    EyeHandMode eyeHand = EyeHandMode::EyeInHand;
    CalibType   calibType = CalibType::Marker;
    MarkerType  markerType = MarkerType::ConcentricCircle;

    bool isEyeInHand() const { return eyeHand == EyeHandMode::EyeInHand; }
    bool isEyeToHand() const { return eyeHand == EyeHandMode::EyeToHand; }
    bool isMarker()    const { return calibType == CalibType::Marker; }
    bool isTcpTouch()  const { return calibType == CalibType::TcpTouch; }

    // 见上面的 free function：这两条是同一个判据的成员写法，别在原地再推导一遍。
    bool needsCapturePose() const { return ::needsCapturePose(eyeHand, calibType); }
    bool needsRobotTarget() const { return ::needsRobotTarget(calibType); }

    QString eyeHandStr() const {
        return isEyeInHand() ? QStringLiteral("eye_in_hand") : QStringLiteral("eye_to_hand");
    }
    QString calibTypeStr() const {
        return isMarker() ? QStringLiteral("marker") : QStringLiteral("tcp_touch");
    }
};
