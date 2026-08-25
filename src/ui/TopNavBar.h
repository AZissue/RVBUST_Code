#pragma once
#include <QWidget>
#include <QLabel>
#include <QPushButton>
#include <QProgressBar>

class TopNavBar : public QWidget {
    Q_OBJECT
public:
    explicit TopNavBar(QWidget* parent = nullptr);

    void updateProgress(int current, int total = -1);
    void setCameraStatus(bool connected, const QString& deviceName = {});
    void setConnectBusy(bool busy, const QString& text);

signals:
    void settingsClicked();
    void helpClicked();
    void connectCameraClicked();
    void disconnectCameraClicked();

private slots:
    void onConnectBtnClicked();

private:
    QLabel* m_title;
    QLabel* m_progressLabel;
    QProgressBar* m_progressBar;
    QLabel* m_cameraDot;
    QLabel* m_cameraLabel;
    QPushButton* m_btnConnect;
    QPushButton* m_btnSettings;
    QPushButton* m_btnHelp;
    bool m_cameraConnected = false;
};
