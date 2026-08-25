#pragma once
#include <QWidget>
#include <QPushButton>

class ActionButtons : public QWidget {
    Q_OBJECT
public:
    explicit ActionButtons(QWidget* parent = nullptr);

    enum class BusyTarget { Capture, Detect, Save, Undo, Preview, Calc };
    void setBusy(BusyTarget target, const QString& text);
    void clearBusy();
    void setCaptureEnabled(bool enabled);
    void setDetectEnabled(bool enabled);
    void setSaveEnabled(bool enabled);
    void setUndoEnabled(bool enabled);
    void setCalcEnabled(bool enabled);
    void setPreviewActive(bool active);
    void setPreviewEnabled(bool enabled);

signals:
    void captureClicked();
    void detectClicked();
    void saveClicked();
    void undoClicked();
    void calcClicked();
    void previewToggled(bool on);

private:
    void applyEnabledStates();
    QPushButton* buttonFor(BusyTarget target) const;
    void applyPreviewStyle();
    void applyBaseStyle(QPushButton* btn);
    void flash(QPushButton* btn);

    QPushButton* m_btnPreview;
    QPushButton* m_btnCapture;
    QPushButton* m_btnDetect;
    QPushButton* m_btnSave;
    QPushButton* m_btnUndo;
    QPushButton* m_btnCalc;
    bool m_busy = false;
    BusyTarget m_busyTarget = BusyTarget::Capture;
    bool m_previewActive = false;
    bool m_captureEnabled = true;
    bool m_detectEnabled = false;
    bool m_saveEnabled = false;
    bool m_undoEnabled = false;
    bool m_calcEnabled = false;
    bool m_previewEnabled = false;

    QTimer* m_busyTimeout = nullptr;  // safety: auto-clear stuck busy state
    QTimer* m_flashTimer = nullptr;
    QPushButton* m_flashButton = nullptr;
};
