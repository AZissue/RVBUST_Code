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
    void plyReaderSkipsNonVertexScalarProperties();
    // T-004（Codex 验收测试）：头部声称的点数远超文件实际内容时，解析器必须
    // 报错返回，而不是先按声称值 reserve() 再被 bad_alloc 带走整个进程。
    void plyReaderRejectsOversizedVertexCount();
    void plyReaderRejectsShortBinaryWithBigClaim();
};
