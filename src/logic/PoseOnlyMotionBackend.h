#pragma once

// ── 只读位姿品牌后端（Modbus TCP / 博纳斯 JSON / 埃夫特 SDK）────────────
//
// 「机器人通信」合并进「机器人控制」后，控制台的下拉里必须仍然支持这些
// 品牌。它们没有运动接口，但都实现同一个 `RobotPose::Reader`，所以一个
// 品牌一个后端对象、各自持有自己的 Reader 与协议文案：
//
//   * 连接与轮询在**自己的工作线程**里（阻塞的 waitForConnected/读 socket
//     绝不能碰 UI 线程）；
//   * 50 ms 读一次位姿，用 `poseUpdated(mm/度)` 推出，控制台/拍照节点/卡片
//     都消费这一份；
//   * `supportsMotion() == false`：控制台隐藏运动区；若程序里仍有移动节点，
//     调用会明确失败（`motionFinished(false, ...)`），不会静默跳过；
//   * 使能是空操作（没有运动可许可），`isEnabled()` 跟随连接状态。
#include <QObject>
#include <QString>
#include <QThread>

#include <functional>
#include <memory>

#include "logic/RobotMotionBackend.h"
#include "logic/RobotPose.h"

class QTimer;

class PoseOnlyWorker : public QObject {
    Q_OBJECT
public:
    // 传入的 reader 归 worker 所有；configure 在每次 start() 时于 worker
    // 线程里调用（Modbus 用它设置寄存器格式/系数/站号）。
    using Configure = std::function<void(const RobotMotion::ConnectOptions&)>;

    PoseOnlyWorker(std::unique_ptr<RobotPose::Reader> reader, QString protocol,
                   Configure configure, bool usePort, QObject* parent = nullptr);

    // 以下方法只在 worker 线程调用（后端用队列连接投递）。
    void start(const RobotMotion::ConnectOptions& options);
    void shutdown();
    void poll();

signals:
    void connectedChanged(bool connected);
    void poseUpdated(const RobotMotion::State& state);
    void statusMessage(const QString& text, bool error);

private:
    std::unique_ptr<RobotPose::Reader> m_reader;
    QString m_protocol;          // 例：Modbus TCP / 博纳斯 JSON/TCP
    Configure m_configure;
    bool m_usePort = true;       // 埃夫特端口由 SDK 固定，不传
    bool m_connected = false;
    bool m_reportedReadError = false;
    QString m_label;             // 「host:port，协议」——连接后的提示用
    QTimer* m_timer = nullptr;
};

class PoseOnlyMotionBackend : public RobotMotionBackend {
    Q_OBJECT
public:
    enum class Kind { Modbus, NrcJson, Efort };

    explicit PoseOnlyMotionBackend(Kind kind, QObject* parent = nullptr);
    ~PoseOnlyMotionBackend() override;

    Kind kind() const { return m_kind; }
    QString name() const override;
    bool isSimulated() const override { return false; }
    bool supportsMotion() const override { return false; }
    bool isConnected() const override { return m_connected; }
    // 没有运动可许可：连上即可用。控制台在只读品牌下隐藏使能按钮。
    bool isEnabled() const override { return m_connected; }
    RobotMotion::State state() const override { return m_state; }

public slots:
    void connectDevice(const QString& host, quint16 port) override;
    void connectDevice(const RobotMotion::ConnectOptions& options) override;
    void disconnectDevice() override;
    void setEnabled(bool enabled) override;
    void moveCartesian(const RobotMotion::Pose& target, double speedPct,
                       double toleranceMm = 2.0, double toleranceDeg = 1.0,
                       int timeoutMs = 15000) override;
    void moveJoint(const RobotMotion::Pose& target, double speedPct,
                   double toleranceDeg = 1.0, int timeoutMs = 15000) override;
    void jogCartesian(int axis, double delta, double speedPct) override;
    void jogJoint(int axis, double delta, double speedPct) override;
    void moveJointAxisTo(int axis, double degrees, double speedPct) override;
    void stopMotion() override;

private:
    void refuseMotion();

    Kind m_kind;
    QThread* m_thread = nullptr;
    PoseOnlyWorker* m_worker = nullptr;
    RobotMotion::State m_state;
    bool m_connected = false;
};
