#pragma once

#include <QObject>

class TestCalibrationService : public QObject {
    Q_OBJECT
private slots:
    void normalizePoseLineAcceptsSpacesAndCommas();
    void normalizePoseLineRejectsBadInput();
    void errorTextMapping();
};
