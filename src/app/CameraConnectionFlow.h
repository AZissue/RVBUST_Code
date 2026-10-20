#pragma once

#include <QObject>
#include <QString>
#include <vector>

#include "logic/CameraManager.h"

// Camera connection state machine: device enumeration, the startup pre-scan and
// the "user clicked 连接 while the pre-scan is still running" case.
//
// Before this class those three flags lived on MainWindow
// (m_preScanning / m_cachedDevices / m_connectRequested) and were written from
// three different entry points.  They now have exactly one owner; MainWindow
// only reacts to the two signals and shows the device dialog.
//
// Threading: everything runs on the UI thread (CameraManager::prewarmSystem
// must run there; the enumeration itself is already async inside
// CameraManager::scanDevicesAsync).  The selected device is still connected by
// MainWindow, because the RVC camera object has to be created on the thread
// that later drives the preview.
class CameraConnectionFlow : public QObject {
    Q_OBJECT
public:
    explicit CameraConnectionFlow(CameraManager* camera, QObject* parent = nullptr);

    // Startup background scan.  Caches the device list; if the user asked to
    // connect while it was running, the pending request is answered instead.
    void preScan();

    // The user pressed 连接.  Emits scanStarted() when an enumeration has to
    // run (so the caller can show the busy state), then exactly one
    // devicesReady() with the list to present.
    void requestConnect();

    // Drop the cache and re-enumerate (after "释放相机"): the bus scan is what
    // makes the next 连接 go straight to Open().  Emits rescanned(count) when
    // the scan finishes.
    void refreshCache();

    bool isPreScanning() const { return m_preScanning; }
    const std::vector<DeviceEntry>& cachedDevices() const { return m_cachedDevices; }

signals:
    // "正在搜索相机..." — the caller sets its busy state.
    void scanStarted();
    void rescanned(int deviceCount);
    // devices may be empty (caller shows the "not found" toast).  Emitted on
    // the UI thread after either the pre-scan or a fresh enumeration finished.
    void devicesReady(const std::vector<DeviceEntry>& devices);

private:
    void scanNow();

    CameraManager* m_camera = nullptr;
    std::vector<DeviceEntry> m_cachedDevices;
    bool m_preScanning = false;
    bool m_connectRequested = false;
};
