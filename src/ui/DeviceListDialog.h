#pragma once
#include <QDialog>
#include <QTableWidget>
#include <QPushButton>
#include <QFutureWatcher>
#include <vector>
#include <functional>
#include "logic/CameraManager.h"  // for DeviceEntry

class DeviceListDialog : public QDialog {
    Q_OBJECT
public:
    explicit DeviceListDialog(QWidget* parent,
                              const std::vector<DeviceEntry>& devices,
                              std::function<std::vector<DeviceEntry>()> refreshFn);

    QString selectedSerial() const;

private slots:
    void onSelectionChanged();
    void onRefresh();
    void onRefreshFinished();
    void onDoubleClicked(int row, int col);

private:
    void buildUi(const std::vector<DeviceEntry>& devices);
    void populateTable(const std::vector<DeviceEntry>& devices);

    QTableWidget* m_table = nullptr;
    QPushButton*  m_btnOk = nullptr;
    QPushButton*  m_btnRefresh = nullptr;
    std::function<std::vector<DeviceEntry>()> m_refreshFn;
    QString m_selectedSerial;
    QFutureWatcher<std::vector<DeviceEntry>>* m_refreshWatcher = nullptr;
    bool m_refreshing = false;
};
