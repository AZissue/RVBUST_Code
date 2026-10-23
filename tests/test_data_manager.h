#pragma once

#include <QObject>

class TestDataManager : public QObject {
    Q_OBJECT
private slots:
    void backupRoundTripResolvesRelativePaths();
    void noSessionConfigJsonWritten();
    void malformedBackupLeavesSessionUntouched();
    void backupWithoutRecordsArrayRejected();
    void unsupportedVersionRejected();
    void missingModeFieldsRejected();
    void outsidePathRejectedAtomically();
    void legacyAbsolutePathInsideSessionAccepted();
    void pathContainment();
    void clearAllOnlyDeletesInsideSession();
    void findLatestBackupSkipsInvalid();
};
