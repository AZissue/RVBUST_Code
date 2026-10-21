#pragma once

// ── 3D 孔洞（圆环拟合 + 孔径 合并，第 17 阶段）────────────────────────────
//
// 用户要求把「圆环拟合」（材料外缘）与「孔径(孔洞边界法)」（孔壁内缘）合并成
// 一个工具，并按 MyUIdesign/2.html 的版式实现界面。两者本来共用
// MeasureTools::measureBoundaryCircle()，只差 materialInside 一个布尔值：
// 本页的「探测方向」下拉框就决定它。
//
// 这是唯一一个**自绘整页**的测量页：不建基类的通用表单/结果表/序列区，
// 但仍复用基类的 ROI 取点、算法调用（runMeasurement）与快照发布，所以
// 2D/3D 叠加、3D 偏差着色与其它测量页完全一致。
#include <vector>

#include "logic/MeasureTools.h"
#include "ui/MeasurePage.h"

class QAbstractButton;
class QComboBox;
class QDoubleSpinBox;
class QLabel;
class QLineEdit;
class QPushButton;
class QStackedWidget;
class QVBoxLayout;

class Hole3DPage : public MeasurePage {
    Q_OBJECT
public:
    explicit Hole3DPage(QWidget* parent = nullptr);

    // 基类的勾选框在本页不存在：3D 工具栏的同步入口改为驱动页内的开关。
    void setDeviationColoring(bool on) override;
    // 新一帧点云 / 新一轮测量：结果面板回到「等待测量」。
    void resetResult() override;
    // 改 3D 着色开关会重算（不写日志）：重算后要把数值重新画回来。
    void rerun() override;

protected:
    void compute(MeasureContext& ctx) override;
    bool wantsDeviationColors() const override;
    bool eventFilter(QObject* watched, QEvent* event) override;

private:
    void buildUi();
    QWidget* buildHeader();
    QWidget* buildParamsTab();
    QWidget* buildResultsTab();
    QWidget* buildFooter();
    void switchTab(int index);
    void onMeasure();
    void onAddToSequence();
    void onCancel();
    void applyTolerance();
    void refreshRoiDisplay();
    void updateResultDisplay();
    void updateGeometryDetail();
    void updateSequenceUi();
    void toggleAdvanced();
    void setHint(const QString& text, bool error);
    bool materialInside() const;
    double toleranceLo() const;
    double toleranceHi() const;

    // ── 参数页 ──
    QComboBox* m_source = nullptr;
    QComboBox* m_mode = nullptr;
    QComboBox* m_direction = nullptr;
    QComboBox* m_geometry = nullptr;
    QLineEdit* m_start[3] = { nullptr, nullptr, nullptr };
    QLineEdit* m_end[3] = { nullptr, nullptr, nullptr };
    QLabel* m_roiState = nullptr;
    QDoubleSpinBox* m_tolLoOff = nullptr;
    QDoubleSpinBox* m_tolNominal = nullptr;
    QDoubleSpinBox* m_tolHiOff = nullptr;
    QWidget* m_advancedHeader = nullptr;
    QWidget* m_advancedBody = nullptr;
    QLabel* m_advancedArrow = nullptr;
    QAbstractButton* m_devColor = nullptr;
    QDoubleSpinBox* m_angle = nullptr;

    // ── 结果页 ──
    QStackedWidget* m_tabs = nullptr;
    QPushButton* m_tabParams = nullptr;
    QPushButton* m_tabResults = nullptr;
    QLabel* m_resultTitle = nullptr;
    QLabel* m_resultValue = nullptr;
    QLabel* m_resultUnit = nullptr;
    QLabel* m_resultDetail = nullptr;
    QLabel* m_resultTag = nullptr;
    QLabel* m_seqCount = nullptr;
    QLabel* m_statMax = nullptr;
    QLabel* m_statMin = nullptr;
    QLabel* m_statAvg = nullptr;
    QLabel* m_statRange = nullptr;
    QVBoxLayout* m_historyLayout = nullptr;
    QWidget* m_historyHost = nullptr;

    // ── 底栏 ──
    QPushButton* m_addButton = nullptr;
    QLabel* m_hint = nullptr;

    // ── 最近一次成功测量的中间量（结果页显示用）──
    double m_lastRadius = 0.0;
    double m_lastRoundness = 0.0;
    double m_lastCoverage = 0.0;
    double m_lastMmPerPx = 0.0;
    int m_lastUsed = 0;
    int m_lastSectors = 0;
    bool m_lastReliable = false;
    bool m_lastSubpixel = false;
    bool m_lastMaterialInside = false;
    MeasureTools::Vec3 m_lastCenter{};

    // 本页「添加到序列」的累积（2.html 的结果面板统计；同时写回共享序列库，
    // 让「重复性」页仍能统计它）。
    std::vector<double> m_sequence;
};
