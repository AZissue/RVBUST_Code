#pragma once

#include <QObject>

class TestFrameBuffer : public QObject {
    Q_OBJECT
private slots:
    void sharesWithoutCopying();
    void makeMovesTheVector();
    void byteAccounting();
    void slotPublishReplacesAndReleases();
    void slotGetNeverCopies();
    void emptyBufferIsNotValid();
};
