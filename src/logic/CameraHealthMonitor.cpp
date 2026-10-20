#include "logic/CameraHealthMonitor.h"

#include <QTimer>

CameraHealthMonitor::CameraHealthMonitor(QObject* parent)
    : QObject(parent)
{
    m_reconnectTimer = new QTimer(this);
    m_reconnectTimer->setSingleShot(true);
    m_reconnectTimer->setInterval(m_reconnectIntervalMs);
    connect(m_reconnectTimer, &QTimer::timeout,
            this, &CameraHealthMonitor::reconnectDue);

    m_healthTimer = new QTimer(this);
    m_healthTimer->setInterval(HEALTH_INTERVAL_MS);
    connect(m_healthTimer, &QTimer::timeout,
            this, &CameraHealthMonitor::healthCheckDue);
}

void CameraHealthMonitor::setHealthInterval(int ms)
{
    m_healthTimer->setInterval(ms > 0 ? ms : HEALTH_INTERVAL_MS);
}

int CameraHealthMonitor::healthInterval() const
{
    return m_healthTimer->interval();
}

void CameraHealthMonitor::startHealthChecks()
{
    m_healthTimer->start();
}

void CameraHealthMonitor::stop()
{
    m_reconnectTimer->stop();
    m_healthTimer->stop();
    m_attempts = 0;
}

void CameraHealthMonitor::setReconnectInterval(int ms)
{
    m_reconnectIntervalMs = ms > 0 ? ms : RECONNECT_INTERVAL_MS;
}

CameraHealthMonitor::ReconnectPlan CameraHealthMonitor::planReconnect()
{
    if (m_reconnectTimer->isActive())
        return ReconnectPlan::Ignored;

    if (m_attempts >= MAX_ATTEMPTS) {
        m_attempts = 0;
        return ReconnectPlan::Exhausted;
    }

    ++m_attempts;
    m_reconnectTimer->start(m_reconnectIntervalMs);
    return ReconnectPlan::Scheduled;
}

void CameraHealthMonitor::noteConnected()
{
    m_attempts = 0;
}
