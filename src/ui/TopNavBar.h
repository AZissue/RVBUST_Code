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
    // 「新建会话」: 只在当前会话已有记录、且没有任务在跑时可点。
    void setNewSessionEnabled(bool enabled);

signals:
    void settingsClicked();
    void helpClicked();
    void connectCameraClicked();
    void disconnectCameraClicked();
    void newSessionClicked();

private slots:
    void onConnectBtnClicked();

private:
    QLabel* m_title;
    QLabel* m_progressLabel;
    QProgressBar* m_progressBar;
    QLabel* m_cameraDot;
    QLabel* m_cameraLabel;
    QPushButton* m_btnConnect;
    QPushButton* m_btnNewSession;
    QPushButton* m_btnSettings;
    QPushButton* m_btnHelp;
    bool m_cameraConnected = false;
};
