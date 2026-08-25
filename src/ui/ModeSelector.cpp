#include "ui/ModeSelector.h"
#include "ui/Theme.h"
#include <QHBoxLayout>
#include <QLabel>
#include <cmath>
#include <algorithm>

ModeSelector::ModeSelector(QWidget* parent)
    : QWidget(parent)
{
    setStyleSheet(QStringLiteral("background-color: %1;").arg(Theme::BG_MAIN));

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(24, 4, 24, 4);
    layout->setSpacing(0);

    // Single row: 手眼模式 + 标定方法 + 标记物类型
    auto* row1 = new QHBoxLayout();
    row1->setSpacing(14);

    // Tools entry lives next to the mode row (left), pushing the calibration
    // selectors to the right.
    m_btnTools = new QPushButton(QStringLiteral("工具"), this);
    m_btnTools->setFixedSize(56, 28);
    m_btnTools->setStyleSheet(QStringLiteral(
        "QPushButton { color: %1; background: transparent; border: 1px solid %2;"
        " border-radius: 4px; font-size: %3px; font-weight: 600; }"
        "QPushButton:hover { border-color: %4; color: %4; }")
        .arg(Theme::TEXT_BODY).arg(Theme::BORDER_DEFAULT)
        .arg(Theme::FONT_HINT).arg(Theme::PRIMARY));
    row1->addWidget(m_btnTools);
    row1->addSpacing(25);
    connect(m_btnTools, &QPushButton::clicked, this, &ModeSelector::toolsClicked);

    // Group 1: Eye-hand mode
    auto* group1 = new QHBoxLayout();
    group1->setSpacing(6);
    auto* lbl1 = new QLabel(QStringLiteral("手眼模式："), this);
    lbl1->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; font-weight: 500; border: none;")
                        .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    group1->addWidget(lbl1);

    m_eyeHandGroup = new QButtonGroup(this);
    m_eyeHandGroup->setExclusive(true);
    m_btnEyeToHand = makeToggle(QStringLiteral("眼在手外"), m_eyeHandGroup, 0, true);
    m_btnEyeInHand = makeToggle(QStringLiteral("眼在手上"), m_eyeHandGroup, 1, false);
    group1->addWidget(m_btnEyeToHand);
    group1->addWidget(m_btnEyeInHand);
    row1->addLayout(group1);

    // Group 2: Calibration method
    auto* group2 = new QHBoxLayout();
    group2->setSpacing(6);
    auto* lbl2 = new QLabel(QStringLiteral("标定方法："), this);
    lbl2->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; font-weight: 500; border: none;")
                        .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    group2->addWidget(lbl2);

    m_calibTypeGroup = new QButtonGroup(this);
    m_calibTypeGroup->setExclusive(true);
    m_btnMarker = makeToggle(QStringLiteral("标记物标定"), m_calibTypeGroup, 0, true);
    m_btnMarker->setToolTip(QStringLiteral("使用标记物进行手眼标定"));
    m_btnTcp    = makeToggle(QStringLiteral("戳点标定"), m_calibTypeGroup, 1, false);
    m_btnTcp->setToolTip(QStringLiteral("使用机器人TCP戳点进行手眼标定"));
    group2->addWidget(m_btnMarker);
    group2->addWidget(m_btnTcp);
    row1->addLayout(group2);

    // Group 3: Marker type (visible only when 标记物标定 selected)
    m_markerTypeGroup = new QButtonGroup(this);
    m_markerTypeGroup->setExclusive(true);

    auto* group3 = new QHBoxLayout();
    group3->setSpacing(6);
    auto* lbl3 = new QLabel(QStringLiteral("标记物类型："), this);
    lbl3->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; font-weight: 500; border: none;")
                        .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    m_markerTypeLabel = lbl3;
    group3->addWidget(lbl3);

    m_btnConcentric = makeToggle(QStringLiteral("同心圆"), m_markerTypeGroup, 0, true);
    m_btnConcentric->setToolTip(QStringLiteral("同心圆标记物 — 使用RVC原生检测"));
    m_btnAsymmetricGrid = makeToggle(QStringLiteral("黑底白圆"), m_markerTypeGroup, 1, false);
    m_btnAsymmetricGrid->setToolTip(QStringLiteral("黑底白圆非对称标定板 — 使用HandEyeSDK检测"));
    group3->addWidget(m_btnConcentric);
    group3->addWidget(m_btnAsymmetricGrid);

    // Caliboard pattern + spec dropdowns (visible only when 黑底白圆 selected)
    m_caliboardSpecsWidget = new QWidget(this);
    auto* specLayout = new QHBoxLayout(m_caliboardSpecsWidget);
    specLayout->setContentsMargins(0, 0, 0, 0);
    specLayout->setSpacing(8);

    // Pattern: 4×5 / 4×11 / 7×11
    auto* patternLabel = new QLabel(QStringLiteral("规格："), m_caliboardSpecsWidget);
    patternLabel->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; font-weight: 500; border: none;")
                                .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    specLayout->addWidget(patternLabel);

    m_patternCombo = new QComboBox(m_caliboardSpecsWidget);
    m_patternCombo->addItem(QStringLiteral("4 × 5"),   QVariantList{4, 5});
    m_patternCombo->addItem(QStringLiteral("4 × 11"),  QVariantList{4, 11});
    m_patternCombo->addItem(QStringLiteral("7 × 11"),  QVariantList{7, 11});
    m_patternCombo->setFixedWidth(90);
    m_patternCombo->setStyleSheet(Theme::comboBoxStyle());
    specLayout->addWidget(m_patternCombo);

    // Size spec: A0-A10 → auto circleStep
    auto* specLabel = new QLabel(QStringLiteral("尺寸："), m_caliboardSpecsWidget);
    specLabel->setStyleSheet(QStringLiteral("font-size: %1px; color: %2; font-weight: 500; border: none;")
                             .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    specLayout->addWidget(specLabel);

    struct SpecEntry { const char* label; float step; };
    static const SpecEntry specs[] = {
        {"A0", 160}, {"A1", 112}, {"A2", 80}, {"A3", 56}, {"A4", 40},
        {"A5", 28},  {"A6", 20},  {"A7", 14}, {"A8", 10}, {"A9", 7}, {"A10", 4.8f},
    };
    m_specCombo = new QComboBox(m_caliboardSpecsWidget);
    for (const auto& s : specs)
        m_specCombo->addItem(QString::fromLatin1(s.label), s.step);
    m_specCombo->setCurrentIndex(9);  // default A9
    m_specCombo->setFixedWidth(80);
    m_specCombo->setStyleSheet(Theme::comboBoxStyle());
    specLayout->addWidget(m_specCombo);
    specLayout->addStretch();

    // Wrap group3 in a widget so we can show/hide it as a unit
    m_markerTypeGroupWidget = new QWidget(this);
    // Caliboard specs sit to the RIGHT of the marker-type buttons on the
    // same horizontal line (there is spare room next to the buttons).
    auto* markerTypeLayout = new QHBoxLayout(m_markerTypeGroupWidget);
    markerTypeLayout->setContentsMargins(0, 0, 0, 0);
    markerTypeLayout->setSpacing(14);
    markerTypeLayout->addLayout(group3);
    markerTypeLayout->addWidget(m_caliboardSpecsWidget);
    row1->addWidget(m_markerTypeGroupWidget);

    // Hide caliboard specs initially (同心圆 is default)
    m_caliboardSpecsWidget->setVisible(false);

    row1->addStretch();
    layout->addLayout(row1);

    // Connections
    connect(m_eyeHandGroup,  QOverload<int>::of(&QButtonGroup::buttonClicked),
            this, &ModeSelector::onEyeHandChanged);
    connect(m_calibTypeGroup, QOverload<int>::of(&QButtonGroup::buttonClicked),
            this, &ModeSelector::onCalibTypeChanged);
    connect(m_markerTypeGroup, QOverload<int>::of(&QButtonGroup::buttonClicked),
            this, &ModeSelector::onMarkerTypeChanged);
    connect(m_patternCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &ModeSelector::onCaliboardSpecChanged);
    connect(m_specCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, &ModeSelector::onCaliboardSpecChanged);
}

QPushButton* ModeSelector::makeToggle(const QString& text, QButtonGroup* group, int id, bool selected)
{
    auto* btn = new QPushButton(text, this);
    btn->setCheckable(true);
    // Adaptive width: fit the label tightly so the buttons read as one group
    // instead of looking like separate controls.
    btn->setFixedHeight(32);
    const int textW = btn->fontMetrics().horizontalAdvance(text);
    btn->setFixedWidth(std::max(72, textW + 24));
    btn->setChecked(selected);
    if (selected)
        btn->setStyleSheet(Theme::toggleSelectedStyle());
    else
        btn->setStyleSheet(Theme::toggleUnselectedStyle());
    group->addButton(btn, id);
    return btn;
}

std::pair<bool, bool> ModeSelector::currentMode() const
{
    return {m_btnEyeInHand->isChecked(), m_btnMarker->isChecked()};
}

bool ModeSelector::isMarkerConcentric() const
{
    return m_btnConcentric->isChecked();
}

void ModeSelector::setMode(bool eyeInHand, bool markerType, bool concentric)
{
    (eyeInHand ? m_btnEyeInHand : m_btnEyeToHand)->setChecked(true);
    (markerType ? m_btnMarker : m_btnTcp)->setChecked(true);
    (concentric ? m_btnConcentric : m_btnAsymmetricGrid)->setChecked(true);

    m_btnEyeToHand->setStyleSheet(eyeInHand ? Theme::toggleUnselectedStyle() : Theme::toggleSelectedStyle());
    m_btnEyeInHand->setStyleSheet(eyeInHand ? Theme::toggleSelectedStyle() : Theme::toggleUnselectedStyle());
    m_btnMarker->setStyleSheet(markerType ? Theme::toggleSelectedStyle() : Theme::toggleUnselectedStyle());
    m_btnTcp->setStyleSheet(markerType ? Theme::toggleUnselectedStyle() : Theme::toggleSelectedStyle());
    m_btnConcentric->setStyleSheet(concentric ? Theme::toggleSelectedStyle() : Theme::toggleUnselectedStyle());
    m_btnAsymmetricGrid->setStyleSheet(concentric ? Theme::toggleUnselectedStyle() : Theme::toggleSelectedStyle());

    m_markerTypeGroupWidget->setVisible(true);
    updateCaliboardWidgetsVisibility();}

void ModeSelector::onEyeHandChanged(int id)
{
    bool eyeInHand = (id == 1);
    m_btnEyeToHand->setStyleSheet(eyeInHand ? Theme::toggleUnselectedStyle() : Theme::toggleSelectedStyle());
    m_btnEyeInHand->setStyleSheet(eyeInHand ? Theme::toggleSelectedStyle() : Theme::toggleUnselectedStyle());
    emit modeChanged(eyeInHand, m_btnMarker->isChecked(), m_btnConcentric->isChecked());
}

void ModeSelector::onCalibTypeChanged(int id)
{
    bool marker = (id == 0);
    m_btnMarker->setStyleSheet(marker ? Theme::toggleSelectedStyle() : Theme::toggleUnselectedStyle());
    m_btnTcp->setStyleSheet(marker ? Theme::toggleUnselectedStyle() : Theme::toggleSelectedStyle());
    emit modeChanged(m_btnEyeInHand->isChecked(), marker, m_btnConcentric->isChecked());
}

void ModeSelector::onMarkerTypeChanged(int id)
{
    bool concentric = (id == 0);
    m_btnConcentric->setStyleSheet(concentric ? Theme::toggleSelectedStyle() : Theme::toggleUnselectedStyle());
    m_btnAsymmetricGrid->setStyleSheet(concentric ? Theme::toggleUnselectedStyle() : Theme::toggleSelectedStyle());
    updateCaliboardWidgetsVisibility();
    emit modeChanged(m_btnEyeInHand->isChecked(), m_btnMarker->isChecked(), concentric);
    if (!concentric)
        emit caliboardParamsChanged(caliboardPatternW(), caliboardPatternH(), caliboardCircleStep());
}

void ModeSelector::updateCaliboardWidgetsVisibility()
{
    m_caliboardSpecsWidget->setVisible(!m_btnConcentric->isChecked());
}

void ModeSelector::onCaliboardSpecChanged()
{
    emit caliboardParamsChanged(caliboardPatternW(), caliboardPatternH(), caliboardCircleStep());
}

int ModeSelector::caliboardPatternW() const
{
    auto data = m_patternCombo->currentData().value<QVariantList>();
    return data.size() >= 2 ? data[0].toInt() : 4;  // columns (short side)
}

int ModeSelector::caliboardPatternH() const
{
    auto data = m_patternCombo->currentData().value<QVariantList>();
    return data.size() >= 2 ? data[1].toInt() : 11;  // rows (long side, must be odd)
}

float ModeSelector::caliboardCircleStep() const
{
    return m_specCombo->currentData().toFloat();
}

void ModeSelector::setCaliboardParams(int patternW, int patternH, float circleStep)
{
    bool patternFound = false;
    for (int i = 0; i < m_patternCombo->count(); ++i) {
        auto data = m_patternCombo->itemData(i).value<QVariantList>();
        if (data.size() >= 2 && data[0].toInt() == patternW && data[1].toInt() == patternH) {
            m_patternCombo->setCurrentIndex(i);
            patternFound = true;
            break;
        }
    }
    if (!patternFound) {
        // Configured pattern not available — fall back to "4 × 11"
        m_patternCombo->setCurrentIndex(1);
    }
    // Find closest spec match
    int bestIdx = -1;
    float bestDiff = 1e9f;
    for (int i = 0; i < m_specCombo->count(); ++i) {
        float diff = std::abs(m_specCombo->itemData(i).toFloat() - circleStep);
        if (diff < bestDiff) { bestDiff = diff; bestIdx = i; }
    }
    if (bestIdx >= 0)
        m_specCombo->setCurrentIndex(bestIdx);
}
