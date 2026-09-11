#pragma once

#include <QObject>

class TestBoardPoseFit : public QObject {
    Q_OBJECT
private slots:
    void fitXyPlane();
    void fitTiltedPlane();
    void fitDegenerate();
    void fitSkipsInvalidPoints();
    void quatRoundtrip();
};
