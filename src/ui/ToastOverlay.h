#pragma once
#include <QWidget>
#include <QLabel>
#include <QTimer>

class ToastOverlay : public QWidget {
    Q_OBJECT
public:
    explicit ToastOverlay(QWidget* parent = nullptr);

    void showMessage(const QString& text, bool success = true, int durationMs = 3000);

private:
    QLabel* m_label;
    QTimer m_hideTimer;
};
