#pragma once
#include <QWidget>
#include <QPushButton>
#include <QButtonGroup>
#include <QLabel>
#include <QComboBox>

class ModeSelector : public QWidget {
    Q_OBJECT
public:
    explicit ModeSelector(QWidget* parent = nullptr);

    std::pair<bool, bool> currentMode() const; // (eyeInHand, isMarker)
    bool isMarkerConcentric() const;           // true=同心圆, false=黑底白圆
    int caliboardPatternW() const;
    int caliboardPatternH() const;
    float caliboardCircleStep() const;
    void setCaliboardParams(int patternW, int patternH, float circleStep);
    void setMode(bool eyeInHand, bool markerType, bool concentric = true);

signals:
    void modeChanged(bool eyeInHand, bool markerType, bool concentric);
    void caliboardParamsChanged(int patternW, int patternH, float circleStep);
    void toolsClicked();

private slots:
    void onEyeHandChanged(int id);
    void onCalibTypeChanged(int id);
    void onMarkerTypeChanged(int id);
    void onCaliboardSpecChanged();
    void updateCaliboardWidgetsVisibility();

private:
    QPushButton* makeToggle(const QString& text, QButtonGroup* group, int id, bool selected);

    QButtonGroup* m_eyeHandGroup;
    QButtonGroup* m_calibTypeGroup;
    QButtonGroup* m_markerTypeGroup;
    QPushButton* m_btnEyeToHand;
    QPushButton* m_btnEyeInHand;
    QPushButton* m_btnMarker;
    QPushButton* m_btnTcp;
    QPushButton* m_btnConcentric;
    QPushButton* m_btnAsymmetricGrid;
    QPushButton* m_btnTools;
    QWidget* m_markerTypeGroupWidget;
    QLabel* m_markerTypeLabel;
    QWidget* m_caliboardSpecsWidget;
    QComboBox* m_patternCombo;
    QComboBox* m_specCombo;      // A0-A10 → circleStep mapping
};
