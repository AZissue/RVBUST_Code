#pragma once
#include <QWidget>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>

class DataInputCard : public QWidget {
    Q_OBJECT
public:
    explicit DataInputCard(const QString& cardId, const QString& label,
                           const QString& hint = {}, QWidget* parent = nullptr);

    QString cardId() const;
    QString value() const;
    void setValue(const QString& text);
    void setStatus(const QString& status); // "empty", "ok", "error"

protected:
    void resizeEvent(QResizeEvent* event) override;

signals:
    void valueChanged(const QString& text);

private slots:
    void onTextChanged(const QString& text);
    void onCopy();

private:
    QString m_cardId;
    QString m_hint;
    QLabel* m_statusDot;
    QLabel* m_label;
    QLineEdit* m_input;
    QPushButton* m_btnCopy;
};
