#pragma once

#include <QObject>

class TestCameraFrameCache : public QObject {
    Q_OBJECT
private slots:
    void emptyCacheReportsNothing();
    void publishSharesWithoutCopying();
    void republishReleasesThePreviousFrame();
    void correspondAndAlignmentAreReported();
    void bytesIncludeEveryCachedPart();
    void clearDropsEverything();
    void nativeMarkersAreCopied();
};
