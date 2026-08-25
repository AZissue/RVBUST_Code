#pragma once

#include <QObject>

class TestGeometryTools : public QObject {
    Q_OBJECT
private slots:
    void distance3dBasic();
    void distance3dNegativeCoordinates();
    void convertLengthUnits();
    void formatDistancePrecision();
};
