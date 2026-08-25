#pragma once

#include <QObject>

class TestPixelTo3D : public QObject {
    Q_OBJECT
private slots:
    void alignedLookupBasic();
    void alignedLookupOutOfBounds();
    void alignedLookupRejectsNaN();
    void projectedIndexRoundTrip();
    void projectedIndexWithExtrinsics();
    void correspondIndexRoundTrip();
    void plyReaderAscii();
    void plyReaderBinaryFloat();
    void plyReaderBadInputs();
};
