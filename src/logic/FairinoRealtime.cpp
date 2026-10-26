#include "logic/FairinoRealtime.h"

#include <QtEndian>

#include <cmath>
#include <cstring>

namespace FairinoRealtime {

namespace {

quint8 u8(const QByteArray& data, int offset)
{
    return static_cast<quint8>(data.at(offset));
}

qint32 i32le(const QByteArray& data, int offset)
{
    const quint32 raw = qFromLittleEndian<quint32>(
        reinterpret_cast<const uchar*>(data.constData() + offset));
    return static_cast<qint32>(raw);
}

quint16 u16le(const QByteArray& data, int offset)
{
    return qFromLittleEndian<quint16>(
        reinterpret_cast<const uchar*>(data.constData() + offset));
}

double f64le(const QByteArray& data, int offset)
{
    const quint64 raw = qFromLittleEndian<quint64>(
        reinterpret_cast<const uchar*>(data.constData() + offset));
    double value = 0.0;
    std::memcpy(&value, &raw, sizeof(double));
    return value;
}

std::array<double, 6> sixDoubles(const QByteArray& data, int offset)
{
    std::array<double, 6> out{};
    for (int i = 0; i < 6; ++i)
        out[static_cast<std::size_t>(i)] = f64le(data, offset + i * 8);
    return out;
}

} // namespace

bool stateHasFinitePose(const State& state)
{
    for (double v : state.tcp) {
        if (!std::isfinite(v))
            return false;
    }
    for (double v : state.joint) {
        if (!std::isfinite(v))
            return false;
    }
    return true;
}

bool decodeFrame(const QByteArray& frame, State* out)
{
    if (!out || frame.size() < kHeaderBytes + kMinPayloadBytes + kTrailerBytes)
        return false;
    if (u8(frame, 0) != kFrameHead || u8(frame, 1) != kFrameHead)
        return false;

    const int dataLen = u8(frame, 3) | (u8(frame, 4) << 8);
    if (dataLen < kMinPayloadBytes || dataLen + kHeaderBytes + kTrailerBytes
                                          != frame.size()) {
        return false;
    }

    quint32 sum = 0;
    for (int i = 0; i < kHeaderBytes + dataLen; ++i)
        sum += u8(frame, i);
    const quint16 stored = u16le(frame, kHeaderBytes + dataLen);
    // Python compares the unbounded sum with the 16-bit trailer. Masking keeps
    // the same check for frames whose byte sum exceeds 65535 (the controller
    // sends a 16-bit checksum); decode() is still guarded by header + length.
    if ((sum & 0xFFFFu) != stored)
        return false;

    State state;
    state.frameCounter = u8(frame, kFrameCntOffset);
    state.programState = u8(frame, kProgramStateOffset);
    state.robotState = u8(frame, kRobotStateOffset);
    state.mainCode = i32le(frame, kMainCodeOffset);
    state.subCode = i32le(frame, kSubCodeOffset);
    state.robotMode = u8(frame, kRobotModeOffset);
    state.joint = sixDoubles(frame, kJointOffset);
    state.tcp = sixDoubles(frame, kTcpPoseOffset);
    state.flange = sixDoubles(frame, kFlangePoseOffset);
    state.toolId = i32le(frame, kToolOffset);
    state.userId = i32le(frame, kUserOffset);
    state.emergencyStop = u8(frame, kEmergencyStopOffset);
    state.motionDone = i32le(frame, kMotionDoneOffset);
    state.queueLength = i32le(frame, kQueueLengthOffset);
    state.safetyStop0 = u8(frame, kSafetyStop0Offset);
    state.safetyStop1 = u8(frame, kSafetyStop1Offset);
    state.enabled = i32le(frame, kEnabledOffset);
    *out = state;
    return true;
}

void Parser::clear()
{
    m_buffer.clear();
    m_accepted = 0;
    m_badChecksums = 0;
    m_skipped = 0;
}

int Parser::feed(const QByteArray& bytes, State* latest)
{
    m_buffer.append(bytes);
    int accepted = 0;

    while (m_buffer.size() >= kHeaderBytes) {
        // Resync: the header is two 0x5A bytes. Step one byte at a time so a
        // single corrupt byte does not discard an otherwise valid stream.
        if (u8(m_buffer, 0) != kFrameHead || u8(m_buffer, 1) != kFrameHead) {
            m_buffer.remove(0, 1);
            ++m_skipped;
            continue;
        }
        const int dataLen = u8(m_buffer, 3) | (u8(m_buffer, 4) << 8);
        const int total = dataLen + kHeaderBytes + kTrailerBytes;
        if (dataLen < kMinPayloadBytes || total > kMaxFrameBytes) {
            // 0x5A5A inside a payload: not a plausible frame length -> resync.
            m_buffer.remove(0, 1);
            ++m_skipped;
            continue;
        }
        if (m_buffer.size() < total)
            break;   // wait for the rest of this frame

        State state;
        if (decodeFrame(m_buffer.left(total), &state)) {
            ++m_accepted;
            ++accepted;
            if (latest)
                *latest = state;
        } else {
            ++m_badChecksums;
        }
        m_buffer.remove(0, total);
    }

    if (m_buffer.size() > kMaxBufferedBytes) {
        m_skipped += static_cast<quint64>(m_buffer.size());
        m_buffer.clear();   // only possible while badly desynchronised
    }
    return accepted;
}

} // namespace FairinoRealtime
