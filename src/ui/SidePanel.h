#pragma once
#include <QWidget>
#include <QFrame>
#include <QLabel>
#include <QTextEdit>
#include <QPushButton>
#include "models/CaptureRecord.h"

class SidePanel : public QWidget {
    Q_OBJECT
public:
    explicit SidePanel(QWidget* parent = nullptr);

    void setTip(const QString& text, bool isError = false);
    void setCalibrationResult(const QString& text);
    void updateFilePreview(bool eyeInHand, bool markerType,
                           const std::vector<CaptureRecord>& records);

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
