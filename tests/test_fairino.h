#pragma once

#include <QObject>

// 法奥（FAIRINO）集成里不需要真机的部分：
//   * XML-RPC 报文构造/解析、HTTP 应答分帧（Content-Length / chunked / close）；
//   * 20004 状态包解码（偏移、校验、断流重同步）与位姿 Reader（只留最新帧）；
//   * MoveL/MoveJ 的参数顺序与元素个数（与 Python SDK 实测一致）；
//   * 姿态数学（R = Rz·Ry·Rx、万向锁、绕基座轴点动、最短旋转角）。
//
// 真机行为（自动/手动模式、使能应答、motion_done 时机）不在单测里假装，
// 见 reports/阶段23-3.0-法奥机器人集成.md 的现场验收清单。
class TestFairino : public QObject {
    Q_OBJECT
private slots:
    void xmlBuildIncludesMethodAndParams();
    void xmlParsesWrappedArray();
    void xmlParsesMultipleParams();
    void xmlParsesFault();
    void xmlRejectsGarbage();
    void firstErrorCodeRejectsNonInteger();

    void httpContentLengthSplitAcrossReads();
    void httpChunked();
    void httpCloseDelimited();
    void httpRejectsNon200();

    void realtimeDecodesMeasuredOffsets();
    void realtimeParserWaitsForSplitFrame();
    void realtimeParserKeepsNewestOfCoalescedFrames();
    void realtimeParserResyncsAfterGarbage();
    void realtimeRejectsBadChecksum();
    void realtimeRejectsWrongDataLength();

    void moveLArgumentLayout();
    void moveJArgumentLayout();

    void eulerRoundTrip();
    void eulerGimbalLock();
    void rotateAboutBaseAxis();
    void rotationDistanceIsShortestPath();
    void reachedCartesianUsesPositionAndAngle();

    void poseReaderStreamsNewestFrame();
    void poseReaderRejectsZeroPose();
    void poseReaderTimesOutWhenStreamStalls();

    void rpcClientRoundTrip();
    void rpcClientReportsErrorCode();
    void rpcClientReportsFault();
};
