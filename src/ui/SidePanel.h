#pragma once
#include <QWidget>
#include <QFrame>
#include <QLabel>
#include <QTextEdit>
#include <QPushButton>
#include <QComboBox>
#include <QSpinBox>
#include <QLineEdit>
#include <QCheckBox>
#include "models/CaptureRecord.h"

class SidePanel : public QWidget {
    Q_OBJECT
public:
    explicit SidePanel(QWidget* parent = nullptr);

    void setTip(const QString& text, bool isError = false);
    void setCalibrationResult(const QString& text);
    void setRobotStatus(const QString& text, bool ok);
    void setRobotConnected(bool connected);
    void updateFilePreview(bool eyeInHand, bool markerType,
                           const std::vector<CaptureRecord>& records);

signals:
    void robotConnectRequested(const QString& host, quint16 port,
                               int format, double scale,
                               quint8 unitId, quint16 startAddress);
    void robotDisconnectRequested();
    void robotReadRequested();
    void robotAutoReadToggled(bool on);

private:
    // Card 1: Tips
    QFrame* m_tipsCard;
    QLabel* m_tipsContent;

    // Card 2: Notes (collapsible)
    QFrame* m_notesCard;
    QPushButton* m_btnCollapseNotes;
    QWidget* m_notesContent;

    // Card 3: File preview
    QFrame* m_previewCard;
    QTextEdit* m_previewText;
    QPushButton* m_tabCamTarget;
    QPushButton* m_tabRobotPose;
    QPushButton* m_tabRobotTarget;
    QPushButton* m_tabCalibResult;

    // Card 4: robot communication (isolated, off by default)
    QFrame* m_robotCard = nullptr;
    QComboBox* m_robotProtocol = nullptr;
    QLineEdit* m_robotHost = nullptr;
    QSpinBox* m_robotPort = nullptr;
    QSpinBox* m_robotStartAddr = nullptr;
    QComboBox* m_robotFormat = nullptr;
    QLineEdit* m_robotScale = nullptr;
    QSpinBox* m_robotUnitId = nullptr;
    QPushButton* m_btnRobotConnect = nullptr;
    QPushButton* m_btnRobotRead = nullptr;
    QCheckBox* m_robotAutoRead = nullptr;
    QLabel* m_robotStatus = nullptr;

    void showMarkerPreview(const std::vector<CaptureRecord>& records);
    void showTcpPreview(const QString& key, bool eyeInHand,
                        const std::vector<CaptureRecord>& records);
    void showCalibrationResult();

    bool m_eyeInHand = true;
    bool m_markerType = true;
    QString m_activeTab;
    QString m_calibResult;
    std::vector<CaptureRecord> m_cachedRecords;
};
