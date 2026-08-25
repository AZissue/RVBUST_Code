#pragma once

#include <QObject>

class TestPointCloudUtils : public QObject {
    Q_OBJECT
private slots:
    void filtersNanAndZeroPoints();
    void convertsMetersToMillimeters();
    void extractsBgrColorsAsRgb();
    void usesGrayForMonoImage();
    void defaultsToWhiteWithoutImage();
    void projectsLookAtCenterToScreenCenter();
    void projectsOffCenterPointAndRejectsBehindCamera();
};
