#pragma once
#include <QWidget>
#include <QVBoxLayout>
#include "ui/DataInputCard.h"

class DataInputArea : public QWidget {
    Q_OBJECT
public:
    explicit DataInputArea(QWidget* parent = nullptr);

    // isMarkerCalib = 标定板标定（true）/ 戳点标定（false）。
    void updateVisibility(bool eyeInHand, bool isMarkerCalib);
    DataInputCard* card(const QString& id) const;

private:
    DataInputCard* m_cardCamTarget;    // card1: camera target xyz
    DataInputCard* m_cardRobotPose;    // card2: robot capture pose
    DataInputCard* m_cardRobotTarget;  // card3: robot target xyz (TCP only)
    QVBoxLayout* m_layout;
};
