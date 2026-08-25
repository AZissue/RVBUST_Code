#pragma once

#include <QObject>

class TestDataManager : public QObject {
    Q_OBJECT
private slots:
    void backupRoundTripResolvesRelativePaths();
    void noSessionConfigJsonWritten();
};
