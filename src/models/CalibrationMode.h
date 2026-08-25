#pragma once
#include <QString>

enum class EyeHandMode { EyeToHand, EyeInHand };
enum class CalibType { Marker, TcpTouch };
enum class MarkerType { ConcentricCircle, AsymmetricGrid };

struct CalibrationMode {
    EyeHandMode eyeHand = EyeHandMode::EyeInHand;
    CalibType   calibType = CalibType::Marker;
    MarkerType  markerType = MarkerType::ConcentricCircle;

    bool isEyeInHand() const { return eyeHand == EyeHandMode::EyeInHand; }
    bool isEyeToHand() const { return eyeHand == EyeHandMode::EyeToHand; }
    bool isMarker()    const { return calibType == CalibType::Marker; }
    bool isTcpTouch()  const { return calibType == CalibType::TcpTouch; }

    QString eyeHandStr() const {
        return isEyeInHand() ? QStringLiteral("eye_in_hand") : QStringLiteral("eye_to_hand");
    }
    QString calibTypeStr() const {
        return isMarker() ? QStringLiteral("marker") : QStringLiteral("tcp_touch");
    }
};
