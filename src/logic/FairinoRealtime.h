#pragma once

// ── 法奥（FAIRINO）20004 实时状态包（纯解析，可单测）──────────────────
//
// 与 UR 的 30003 一样，法奥控制器在 TCP 20004 上**主动推**状态包；官方 Python
// SDK（fairino v2.1.7.1）正是靠这条流填充 robot_state_pkg，并让
// GetActualTCPPose / GetActualJointPosDegree / GetRobotMotionDone /
// GetRobotEnable 等 getter 全部从这份缓存返回（Robot.py 里 XML-RPC 版本的
// getter 已被注释掉）。因此本程序也以 20004 为位姿/使能/到位判据的唯一来源，
// 不再调用那些"SDK 自己都弃用"的 XML-RPC getter。
//
// 帧格式（Robot.py: robot_state_routine_thread + RobotStatePkg，_pack_=1）：
//   [0..1]  0x5A 0x5A                     帧头
//   [2]     frame_cnt                     帧计数（uint8，会回绕）
//   [3..4]  data_len                      uint16 **小端**
//   [5..]   payload（RobotStatePkg 去掉帧头/data_len）
//   [5+data_len .. +1] checksum           uint16 小端；为前面所有字节之和
//   整帧长度 = data_len + 7
//
// 结构体大小 1236 字节（含末尾 check_sum），故 data_len 通常为 1229。
// 下面的偏移是用 ctypes 对 SDK 里的 RobotStatePkg 实测得到的（v2.1.7.1），
// 不是猜的；字段按 _pack_=1 紧密排列。
//
// 与 UR 相同：这条口是**流**，必须持续排空、只保留最新一帧；否则 socket
// 接收缓冲会一直涨，且 readPose 会永远返回连接后的第一帧。
#include <QByteArray>
#include <QtGlobal>

#include <array>

namespace FairinoRealtime {

constexpr quint8 kFrameHead = 0x5A;
constexpr int kHeaderBytes = 5;
constexpr int kTrailerBytes = 2;
constexpr int kStructBytes = 1236;
constexpr int kChecksumOffset = 1234;
constexpr int kMinPayloadBytes = kStructBytes - kHeaderBytes - kTrailerBytes;
constexpr int kMaxFrameBytes = 64 * 1024;
constexpr int kMaxBufferedBytes = 1 << 20;

// Offsets inside RobotStatePkg (ctypes, _pack_=1).
constexpr int kFrameCntOffset = 2;
constexpr int kProgramStateOffset = 5;
constexpr int kRobotStateOffset = 6;
constexpr int kMainCodeOffset = 7;
constexpr int kSubCodeOffset = 11;
constexpr int kRobotModeOffset = 15;
constexpr int kJointOffset = 16;        // 6 × double, 度
constexpr int kTcpPoseOffset = 64;      // 6 × double, mm + 度
constexpr int kFlangePoseOffset = 112;  // 6 × double, mm + 度
constexpr int kToolOffset = 432;        // int32
constexpr int kUserOffset = 436;        // int32
constexpr int kEmergencyStopOffset = 549;
constexpr int kMotionDoneOffset = 550;  // int32, 0=未完成 1=完成
constexpr int kQueueLengthOffset = 555; // int32, 运动队列缓存长度
constexpr int kSafetyStop0Offset = 564;
constexpr int kSafetyStop1Offset = 565;
constexpr int kEnabledOffset = 771;     // int32, rbtEnableState 0/1

struct State {
    quint8 frameCounter = 0;
    quint8 programState = 0;   // 1 停止 2 运行 3 暂停
    quint8 robotState = 0;     // 1 停止 2 运行 3 暂停 4 拖动
    qint32 mainCode = 0;
    qint32 subCode = 0;
    quint8 robotMode = 0;      // 0 自动 1 手动
    std::array<double, 6> joint{};   // 度
    std::array<double, 6> tcp{};     // mm + 度 (R = Rz·Ry·Rx)
    std::array<double, 6> flange{};  // mm + 度
    qint32 toolId = 0;
    qint32 userId = 0;
    quint8 emergencyStop = 0;
    qint32 motionDone = 0;
    qint32 queueLength = 0;
    quint8 safetyStop0 = 0;
    quint8 safetyStop1 = 0;
    qint32 enabled = 0;
};

bool stateHasFinitePose(const State& state);

// Decode one complete frame (header + payload + checksum). Checks size, header,
// data_len and checksum before reading fields.
bool decodeFrame(const QByteArray& frame, State* out);

// Incremental stream parser. feed() buffers partial frames and consumes every
// complete frame; `latest` receives the newest accepted state.
class Parser {
public:
    void clear();
    int feed(const QByteArray& bytes, State* latest);

    quint64 acceptedFrames() const { return m_accepted; }
    quint64 rejectedChecksums() const { return m_badChecksums; }
    quint64 skippedBytes() const { return m_skipped; }
    int bufferedBytes() const { return m_buffer.size(); }

private:
    QByteArray m_buffer;
    quint64 m_accepted = 0;
    quint64 m_badChecksums = 0;
    quint64 m_skipped = 0;
};

} // namespace FairinoRealtime
