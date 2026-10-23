#pragma once

#include <QObject>

class TestDetectionEngine : public QObject {
    Q_OBJECT
private slots:
    void formatXyzForCardSkipsNanAndPicksFirstValid();
    void formatXyzForCardReturnsEmptyForNoValidPoints();
    void formatXyzForCardFormatsThreeDecimals();
    void formatMarkersForOverlayLabelsAndHighlights();
    void firstValidPoint3dSkipsNan();
    void firstValidPoint3dReturnsEmpty();
    void isValidPoint3dRejectsZeroPlaceholderAndNonFinite();
    void countValidPoints3dCountsUsablePoints();
    void countValidPoints2DCountsLeadingValid();
    void detectConcentricRegressionOnTestData();
};
