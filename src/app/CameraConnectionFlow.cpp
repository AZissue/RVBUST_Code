#include "app/CameraConnectionFlow.h"

#include <QTimer>

CameraConnectionFlow::CameraConnectionFlow(CameraManager* camera, QObject* parent)
    : QObject(parent), m_camera(camera)
{
}

void CameraConnectionFlow::preScan()
{
    if (m_preScanning)
        return;
    m_preScanning = true;
    QTimer::singleShot(0, this, [this]() {
        // SystemInit must run on the UI thread (device objects are created
        // here later); the enumeration itself runs in a worker.
        m_camera->prewarmSystem();
        m_camera->scanDevicesAsync([this](const std::vector<DeviceEntry>& devices) {
            m_preScanning = false;
            m_cachedDevices = devices;
            if (m_connectRequested) {
                m_connectRequested = false;
                emit devicesReady(devices);
            }
        });
    });
}

void CameraConnectionFlow::requestConnect()
{
    if (m_preScanning) {
        // Startup pre-scan still running; continue automatically when done.
        // The caller shows the busy state — no nested event loop here, which
        // could re-enter the very handler that called us.
        m_connectRequested = true;
        emit scanStarted();
        return;
    }
    if (m_cachedDevices.empty()) {
        emit scanStarted();
        scanNow();
        return;
    }
    emit devicesReady(m_cachedDevices);
}

void CameraConnectionFlow::scanNow()
{
    m_camera->scanDevicesAsync([this](const std::vector<DeviceEntry>& devices) {
        m_cachedDevices = devices;
        emit devicesReady(devices);
    });
}

void CameraConnectionFlow::refreshCache()
{
    m_cachedDevices.clear();
    m_camera->scanDevicesAsync([this](const std::vector<DeviceEntry>& devices) {
        m_cachedDevices = devices;
        emit rescanned(static_cast<int>(devices.size()));
    });
}
