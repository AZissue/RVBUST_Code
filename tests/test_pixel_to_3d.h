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
    // T-006（Codex 验收测试）：x/y/z 的**声明类型**必须被尊重。
    // 现状：`readScalar()` 只看字节数——4 字节一律按 IEEE float 重新解释位，
    // 1/2 字节直接返回 0.0——所以二进制文件里的 int / short / ushort / uchar
    // 坐标会静默变成垃圾值或 0。
    void plyReaderAsciiTypedXyz();          // 不变量：ascii 走 strtod，本来就对
    void plyReaderBinaryIntXyz();           // 红：int32 被当成 float 重解释
    void plyReaderBinaryShortUnsignedXyz(); // 红：short/ushort/uchar 全返回 0
    void plyReaderUnknownPropertyNeverSilentlyWrong();  // 追加条：布局不许被悄悄挪位
    // T-008：顶点元素上的 list 属性（`property list uchar int ...`）同样不许
    // 被悄悄丢掉 —— 丢掉它 = 后面的 x/y/z 偏移整体前移 = 静默错值。
    void plyReaderListPropertyNeverSilentlyWrong();
};
