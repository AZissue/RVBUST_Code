#include "ui/MeasurePage.h"

#include "ui/ArrowComboBox.h"
#include "ui/Theme.h"

#include <QCheckBox>
#include <QDoubleSpinBox>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>
#include <algorithm>
#include <cmath>

namespace {

// 说明文案里的小字体标签（P4：说明要短、能看懂，所以直接放在页面上，
// 同时选中方法时写一条 [测量-说明] 进操作日志）。
QLabel* specLabel(const char* text, QWidget* parent)
{
    auto* label = new QLabel(QString::fromUtf8(text), parent);
    label->setWordWrap(true);
    label->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                             .arg(Theme::TEXT_BODY).arg(Theme::FONT_HINT));
    return label;
}

// 操作日志的两条固定前缀（P4）：选中方法时是 [测量-说明]，测完是 [测量-结果]。
// 两者必须分开，否则"我刚测的数字"和"这个方法怎么用"在日志里分不出来。
// 前缀本身定义在 MeasureMethods.h 里（可被单测断言）。
QString chainText(const char* tag, const QString& text)
{
    return QString::fromStdString(MeasureTools::logTagged(tag, text.toStdString()));
}

} // namespace

MeasurePage::MeasurePage(MeasureTools::Method method, QWidget* parent)
    : QWidget(parent)
{
    m_spec = MeasureTools::methodSpec(method);
    buildUi();
}

QString MeasurePage::confidenceFor(int points, double rms)
{
    if (points >= 2000 && (rms < 0.0 || rms <= 0.05))
        return QStringLiteral("高");
    if (points >= 300)
        return QStringLiteral("中");
    return QStringLiteral("低");
}

QString MeasurePage::fmt4(double v)
{
    return QString::number(v, 'f', 4);
}

QString MeasurePage::roiText(int slot) const
{
    const QChar letter(QLatin1Char('A').unicode() + slot);
    if (slot >= m_rects.size() || slot >= 2)
        return QStringLiteral("ROI %1：未选择").arg(letter);
    const QRect r = m_rects[slot];
    return QStringLiteral("ROI %1: (%2,%3)-(%4,%5)，%6 点")
        .arg(letter)
        .arg(r.left()).arg(r.top()).arg(r.right()).arg(r.bottom())
        .arg(static_cast<qulonglong>(m_pts[slot].size()));
}

void MeasurePage::buildUi()
{
    const QString id = QString::fromUtf8(m_spec.id);
    auto* layout = new QVBoxLayout(this);
    layout->setSpacing(10);

    // ── 数据源 + ROI（P3：ROI 需求由方法自己声明）──
    auto* cloudGroup = new QGroupBox(QStringLiteral("数据源"), this);
    auto* cloudForm = new QFormLayout(cloudGroup);
    m_cloudLabel = new QLabel(QStringLiteral("尚未采集（先在主窗口点击「拍照」）"), cloudGroup);
    m_cloudLabel->setObjectName(QStringLiteral("measure_cloud_label_%1").arg(id));
    m_cloudLabel->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                    .arg(Theme::TEXT_BODY).arg(Theme::FONT_HINT));
    cloudForm->addRow(QStringLiteral("当前点云"), m_cloudLabel);

    m_roiReqLabel = new QLabel(
        QString::fromStdString(MeasureTools::roiRequirementText(m_spec.method)), cloudGroup);
    m_roiReqLabel->setObjectName(QStringLiteral("measure_roi_req_%1").arg(id));
    m_roiReqLabel->setWordWrap(true);
    m_roiReqLabel->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                     .arg(Theme::PRIMARY).arg(Theme::FONT_HINT));
    cloudForm->addRow(QStringLiteral("ROI 需求"), m_roiReqLabel);

    m_roiLabel = new QLabel(QString::fromStdString(
                                MeasureTools::roiStateText(m_spec.roiCount, 0)), cloudGroup);
    m_roiLabel->setObjectName(QStringLiteral("measure_roi_label_%1").arg(id));
    m_roiLabel->setWordWrap(true);
    m_roiLabel->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                  .arg(Theme::TEXT_BODY).arg(Theme::FONT_HINT));
    cloudForm->addRow(QStringLiteral("测量区域"), m_roiLabel);

    m_roiNote = new QLabel(cloudGroup);
    m_roiNote->setObjectName(QStringLiteral("measure_roi_note_%1").arg(id));
    m_roiNote->setWordWrap(true);
    m_roiNote->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                 .arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));
    cloudForm->addRow(QString(), m_roiNote);

    m_roiClearBtn = new QPushButton(QStringLiteral("清除区域"), cloudGroup);
    m_roiClearBtn->setObjectName(QStringLiteral("measure_roi_clear_%1").arg(id));
    m_roiClearBtn->setStyleSheet(Theme::secondaryButtonStyle());
    cloudForm->addRow(QString(), m_roiClearBtn);
    layout->addWidget(cloudGroup);

    // ── 说明（P4：用途 / ROI 怎么画 / 输出 / 可信度 / 常见错法）──
    auto* specGroup = new QGroupBox(QStringLiteral("说明"), this);
    specGroup->setObjectName(QStringLiteral("measure_spec_%1").arg(id));
    auto* specForm = new QFormLayout(specGroup);
    specForm->addRow(QStringLiteral("用途"), specLabel(m_spec.purpose, specGroup));
    specForm->addRow(QStringLiteral("ROI 怎么画"), specLabel(m_spec.howTo, specGroup));
    specForm->addRow(QStringLiteral("输出"), specLabel(m_spec.outputs, specGroup));
    specForm->addRow(QStringLiteral("可信度"), specLabel(m_spec.confidence, specGroup));
    specForm->addRow(QStringLiteral("常见错法"), specLabel(m_spec.pitfalls, specGroup));
    layout->addWidget(specGroup);

    // ── 公差 + 运行 ──
    auto* methodGroup = new QGroupBox(QStringLiteral("测量"), this);
    auto* methodForm = new QFormLayout(methodGroup);

    auto* tolRow = new QHBoxLayout();
    m_tolEnable = new QCheckBox(QStringLiteral("启用公差"), methodGroup);
    m_tolEnable->setObjectName(QStringLiteral("measure_tol_enable_%1").arg(id));
    m_tolEnable->setStyleSheet(QStringLiteral("font-size: %1px;").arg(Theme::FONT_HINT));
    tolRow->addWidget(m_tolEnable);
    auto* loLabel = new QLabel(QStringLiteral("下限"), methodGroup);
    loLabel->setStyleSheet(QStringLiteral("font-size: %1px;").arg(Theme::FONT_HINT));
    tolRow->addWidget(loLabel);
    m_tolLo = new QDoubleSpinBox(methodGroup);
    m_tolLo->setObjectName(QStringLiteral("measure_tol_lo_%1").arg(id));
    m_tolLo->setDecimals(4);
    m_tolLo->setRange(-1.0e6, 1.0e6);
    m_tolLo->setValue(-0.05);
    m_tolLo->setStyleSheet(Theme::inputStyle());
    tolRow->addWidget(m_tolLo);
    auto* hiLabel = new QLabel(QStringLiteral("上限"), methodGroup);
    hiLabel->setStyleSheet(QStringLiteral("font-size: %1px;").arg(Theme::FONT_HINT));
    tolRow->addWidget(hiLabel);
    m_tolHi = new QDoubleSpinBox(methodGroup);
    m_tolHi->setObjectName(QStringLiteral("measure_tol_hi_%1").arg(id));
    m_tolHi->setDecimals(4);
    m_tolHi->setRange(-1.0e6, 1.0e6);
    m_tolHi->setValue(0.05);
    m_tolHi->setStyleSheet(Theme::inputStyle());
    tolRow->addWidget(m_tolHi);
    tolRow->addStretch();
    methodForm->addRow(QStringLiteral("公差 (mm)"), tolRow);

    m_devColorBox = new QCheckBox(
        QStringLiteral("3D 偏差着色（在 3D 视窗同步显示测量区域）"), methodGroup);
    m_devColorBox->setObjectName(QStringLiteral("measure_dev3d_%1").arg(id));
    m_devColorBox->setStyleSheet(QStringLiteral("font-size: %1px;").arg(Theme::FONT_HINT));
    methodForm->addRow(QString(), m_devColorBox);

    auto* btnRow = new QHBoxLayout();
    m_runBtn = new QPushButton(m_spec.roiCount > 0 ? QStringLiteral("测量")
                                                  : QStringLiteral("统计"),
                               methodGroup);
    m_runBtn->setObjectName(QStringLiteral("measure_run_%1").arg(id));
    m_runBtn->setStyleSheet(Theme::primaryButtonStyle());
    btnRow->addWidget(m_runBtn);
    m_repeatAddBtn = new QPushButton(QStringLiteral("加入重复性"), methodGroup);
    m_repeatAddBtn->setObjectName(QStringLiteral("measure_repeat_add_%1").arg(id));
    m_repeatAddBtn->setStyleSheet(Theme::secondaryButtonStyle());
    // 重复性页本身就是消费序列的，不需要"把自己加进去"。
    m_repeatAddBtn->setVisible(m_spec.roiCount > 0);
    btnRow->addWidget(m_repeatAddBtn);
    btnRow->addStretch();
    methodForm->addRow(QString(), btnRow);

    m_hint = new QLabel(methodGroup);
    m_hint->setObjectName(QStringLiteral("measure_hint_%1").arg(id));
    m_hint->setWordWrap(true);
    m_hint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                              .arg(Theme::ERROR).arg(Theme::FONT_HINT));
    methodForm->addRow(QString(), m_hint);
    layout->addWidget(methodGroup);

    // ── 结果表 ──
    m_table = new QTableWidget(0, 5, this);
    m_table->setObjectName(QStringLiteral("measure_table_%1").arg(id));
    m_table->setHorizontalHeaderLabels({ QStringLiteral("方法"), QStringLiteral("数值"),
                                         QStringLiteral("单位"), QStringLiteral("点数"),
                                         QStringLiteral("可信度") });
    m_table->verticalHeader()->setVisible(false);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setSelectionMode(QAbstractItemView::NoSelection);
    m_table->horizontalHeader()->setStretchLastSection(true);
    m_table->setStyleSheet(
        QStringLiteral("QTableWidget { background: %1; border: 1px solid %2;"
                       " border-radius: %3px; font-size: %4px; }"
                       "QHeaderView::section { background: %5; border: none;"
                       " padding: 5px; font-size: %4px; }")
            .arg(Theme::BG_CARD).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS)
            .arg(Theme::FONT_HINT).arg(Theme::BG_MAIN));
    layout->addWidget(m_table, 1);

    // ── 重复性序列（序列库由面板持有：跨页共用、跨帧累积，仅内存）──
    auto* seriesGroup = new QGroupBox(QStringLiteral("重复性序列（仅本次运行）"), this);
    auto* seriesForm = new QFormLayout(seriesGroup);
    m_seriesCombo = new ArrowComboBox(seriesGroup);
    m_seriesCombo->setObjectName(QStringLiteral("measure_series_combo_%1").arg(id));
    m_seriesCombo->setStyleSheet(Theme::comboBoxStyle());
    seriesForm->addRow(QStringLiteral("序列"), m_seriesCombo);

    m_seriesSummary = new QLabel(QStringLiteral("—"), seriesGroup);
    m_seriesSummary->setObjectName(QStringLiteral("measure_series_summary_%1").arg(id));
    m_seriesSummary->setWordWrap(true);
    m_seriesSummary->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                       .arg(Theme::TEXT_BODY).arg(Theme::FONT_HINT));
    seriesForm->addRow(QStringLiteral("统计"), m_seriesSummary);

    auto* clearSeriesBtn = new QPushButton(QStringLiteral("清空序列"), seriesGroup);
    clearSeriesBtn->setObjectName(QStringLiteral("measure_series_clear_%1").arg(id));
    clearSeriesBtn->setStyleSheet(Theme::secondaryButtonStyle());
    seriesForm->addRow(QString(), clearSeriesBtn);
    layout->addWidget(seriesGroup);

    connect(m_runBtn, &QPushButton::clicked, this, [this]() { run(true); });
    connect(m_repeatAddBtn, &QPushButton::clicked, this, &MeasurePage::onRepeatAdd);
    connect(m_roiClearBtn, &QPushButton::clicked, this, &MeasurePage::clearRoiRequested);
    connect(clearSeriesBtn, &QPushButton::clicked, this, &MeasurePage::clearSeries);
    connect(m_seriesCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int) { refreshSeriesUi(); });
    // 公差只影响重复性趋势页的判定线，改一下要重发快照（不重算）。
    for (QDoubleSpinBox* spin : { m_tolLo, m_tolHi })
        connect(spin, QOverload<double>::of(&QDoubleSpinBox::valueChanged),
                this, [this](double) { publish(); });
    connect(m_tolEnable, &QCheckBox::toggled, this, [this](bool) { publish(); });
    // 3D 偏差着色开关在主窗口 3D 工具栏上还有一个孪生按钮，两边同步（面板转发）。
    connect(m_devColorBox, &QCheckBox::toggled, this, [this](bool on) {
        emit deviationColoringChanged(on);
        rerun();   // 立刻重算颜色，但不再写一条 [测量-结果]
    });
}

QString MeasurePage::explainLine() const
{
    return chainText(MeasureTools::kExplainLogTag,
                     QString::fromStdString(MeasureTools::methodExplainLine(m_spec.method)));
}

void MeasurePage::setCloud(const FrameBuffer::DoubleBuf& grid, int gridW, int gridH,
                           int imageW, int imageH, const QString& cloudText)
{
    m_grid = grid;   // 引用计数，不拷贝数据
    m_gridW = gridW;
    m_gridH = gridH;
    m_imageW = imageW;
    m_imageH = imageH;
    if (m_cloudLabel)
        m_cloudLabel->setText(cloudText);
    resetResult();
}

void MeasurePage::setRoiRects(const QVector<QRect>& rects, const QString& note)
{
    m_rects = rects;
    for (int i = 0; i < 2; ++i) {
        m_pts[i].clear();
        m_cells[i].clear();
    }
    if (m_grid && m_gridW > 0 && m_gridH > 0 && m_imageW > 0 && m_imageH > 0) {
        for (int i = 0; i < m_spec.roiCount && i < m_rects.size() && i < 2; ++i) {
            const QRect r = m_rects[i];
            // 与校验工装（tests/measure_truth.cpp）同一条链路：
            // 图像像素矩形 -> 网格单元矩形 -> 取点+单元号。
            const MeasureTools::GridRect g = MeasureTools::roiImageToGrid(
                r.left(), r.top(), r.right(), r.bottom(), m_imageW, m_imageH,
                m_gridW, m_gridH);
            if (!g.valid)
                continue;
            m_pts[i] = MeasureTools::pointsInRoiIndexed(*m_grid, m_gridW, m_gridH,
                                                        g.x0, g.y0, g.x1, g.y1,
                                                        &m_cells[i]);
        }
    }
    if (m_roiLabel) {
        QStringList parts;
        for (int i = 0; i < m_spec.roiCount && i < 2; ++i)
            parts << roiText(i);
        m_roiLabel->setText(parts.isEmpty()
            ? QString::fromStdString(MeasureTools::roiStateText(m_spec.roiCount, rects.size()))
            : parts.join(QStringLiteral("；")));
    }
    if (m_roiNote)
        m_roiNote->setText(note);
}

QString MeasurePage::currentSeriesName() const
{
    return m_seriesCombo ? m_seriesCombo->currentText() : QString();
}

const QVector<double>* MeasurePage::currentSeries() const
{
    const QString name = currentSeriesName();
    if (name.isEmpty() || !m_series || !m_series->contains(name))
        return nullptr;
    return &m_series->value(name);
}

void MeasurePage::setSeriesStore(QMap<QString, QVector<double>>* store)
{
    m_series = store;
    refreshSeriesUi();
}

void MeasurePage::setDeviationColoring(bool on)
{
    if (!m_devColorBox || m_devColorBox->isChecked() == on)
        return;
    // 设置勾选状态不得反弹回 deviationColoringChanged（面板是唯一写者）。
    const QSignalBlocker block(m_devColorBox);
    m_devColorBox->setChecked(on);
}

void MeasurePage::rerun()
{
    if (m_hasResult)
        run(false);   // 已经有结果才重算；不写重复的 [测量-结果]
}

bool MeasurePage::deviationColoring() const
{
    return m_devColorBox && m_devColorBox->isChecked();
}

void MeasurePage::resetResult()
{
    if (m_hint)
        m_hint->clear();
    if (m_table)
        m_table->setRowCount(0);
    m_rows.clear();
    m_primaryKey.clear();
    m_primaryValue = 0.0;
    m_hasPrimary = false;
    m_hasResult = false;
    m_primaryIndex = -1;
    m_footer.clear();
    m_devSamples.clear();
    m_devRobust = false;
    m_devClipped = 0;
    m_devLo = m_devHi = 0.0;
    m_annotations.clear();
    m_section.clear();
    m_sectionStep = 0.0;
    m_cloudColors.reset();
    m_hasPlane = false;
    m_hasBox = false;
    m_planePoint = { 0.0, 0.0, 0.0 };
    m_planeNormal = { 0.0, 0.0, 0.0 };
    m_boxMin = { 0.0, 0.0, 0.0 };
    m_boxMax = { 0.0, 0.0, 0.0 };
}

void MeasurePage::showHint(const QString& text, bool error)
{
    if (!m_hint)
        return;
    m_hint->setText(text);
    m_hint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                              .arg(error ? Theme::ERROR : Theme::TEXT_BODY)
                              .arg(Theme::FONT_HINT));
}

void MeasurePage::run(bool logResult)
{
    resetResult();

    if (!m_grid || m_gridW <= 0 || m_gridH <= 0) {
        showHint(QStringLiteral("尚未采集点云：请先在主窗口点击「拍照」。"));
        if (logResult)
            emit logRequested(chainText(MeasureTools::kResultLogTag, QString::fromStdString(
                MeasureTools::resultRefusalLine(m_spec.method, "尚未采集点云"))));
        publish();
        return;
    }

    // ROI 需求（P3.2）：方法声明几个 ROI 就要有几个，缺哪个说哪个。
    for (int i = 0; i < m_spec.roiCount && i < 2; ++i) {
        if (m_pts[i].empty()) {
            const QChar letter(QLatin1Char('A').unicode() + i);
            const char* role = i == 0 ? m_spec.roiA : m_spec.roiB;
            const QString msg = QStringLiteral("请先在 2D 视图上拖框选择 ROI %1（%2）。")
                                    .arg(letter)
                                    .arg(QString::fromUtf8(role ? role : ""));
            showHint(msg);
            if (logResult)
                emit logRequested(chainText(MeasureTools::kResultLogTag, QString::fromStdString(
                    MeasureTools::resultRefusalLine(m_spec.method, msg.toStdString()))));
            publish();
            return;
        }
    }

    MeasureContext ctx;
    ctx.roi = m_pts;
    ctx.roiCells = m_cells;
    ctx.roiRects = &m_rects;
    ctx.gridW = m_gridW;
    ctx.gridH = m_gridH;

    compute(ctx);   // ← 子类唯一的入口

    if (!ctx.refusal.isEmpty()) {
        showHint(ctx.refusal);
        if (logResult)
            emit logRequested(chainText(MeasureTools::kResultLogTag, QString::fromStdString(
                MeasureTools::resultRefusalLine(m_spec.method, ctx.refusal.toStdString()))));
        publish();
        return;
    }

    m_rows = ctx.rows;
    m_primaryKey = ctx.primaryKey;
    m_primaryValue = ctx.primaryValue;
    m_hasPrimary = ctx.hasPrimary;
    m_hasResult = !m_rows.empty();
    m_primaryIndex = -1;
    for (int i = 0; i < static_cast<int>(m_rows.size()); ++i) {
        if (m_rows[static_cast<std::size_t>(i)].method == m_primaryKey) {
            m_primaryIndex = i;
            break;
        }
    }
    if (m_primaryIndex < 0 && !m_rows.empty())
        m_primaryIndex = 0;
    m_footer = ctx.footer;
    // 有偏差图时底部说明行换成色标说明（与旧面板一致）。
    applyDeviation(ctx);

    m_annotations = QVector<Measurement::Annotation>(ctx.annotations.begin(),
                                                     ctx.annotations.end());
    m_section = ctx.section;
    m_sectionStep = ctx.sectionStep;
    m_hasPlane = ctx.hasPlane;
    m_planePoint = ctx.planePoint;
    m_planeNormal = ctx.planeNormal;
    m_hasBox = ctx.hasBox;
    m_boxMin = ctx.boxMin;
    m_boxMax = ctx.boxMax;

    if (m_table) {
        m_table->setRowCount(static_cast<int>(m_rows.size()));
        for (int i = 0; i < static_cast<int>(m_rows.size()); ++i) {
            const Measurement::ResultRow& r = m_rows[static_cast<std::size_t>(i)];
            const QString cols[5] = { r.method, r.value, r.unit,
                                      QString::number(r.points), r.confidence };
            for (int c = 0; c < 5; ++c) {
                auto* item = new QTableWidgetItem(cols[c]);
                if (c >= 1 && c <= 3)
                    item->setTextAlignment(Qt::AlignRight | Qt::AlignVCenter);
                m_table->setItem(i, c, item);
            }
        }
        m_table->resizeColumnsToContents();
    }
    if (m_hint)
        m_hint->clear();

    if (logResult && m_hasResult && m_primaryIndex >= 0
        && m_primaryIndex < static_cast<int>(m_rows.size())) {
        std::vector<MeasureTools::ResultItem> items;
        for (const Measurement::ResultRow& r : m_rows)
            items.push_back({ r.method.toStdString(), r.value.toStdString(),
                              r.unit.toStdString() });
        const Measurement::ResultRow& p = m_rows[static_cast<std::size_t>(m_primaryIndex)];
        QString conf = QStringLiteral("%1 点，%2").arg(p.points).arg(p.confidence);
        if (!ctx.confidenceNote.isEmpty())
            conf += QStringLiteral("；") + ctx.confidenceNote;
        emit logRequested(chainText(MeasureTools::kResultLogTag, QString::fromStdString(
            MeasureTools::resultLine(m_spec.method, items, conf.toStdString()))));
    }

    publish();
}

// 偏差图 + 3D 偏差着色：与旧面板同一套（稳健 ±3σ(MAD) 色标，色标行写进页脚）。
void MeasurePage::applyDeviation(MeasureContext& ctx)
{
    m_devSamples.clear();
    if (!ctx.hasDeviation || ctx.devValues.empty()
        || ctx.devValues.size() != ctx.devCells.size())
        return;

    const int gw = m_gridW;
    if (gw <= 0)
        return;
    m_devSamples.reserve(static_cast<int>(ctx.devValues.size()));
    for (std::size_t k = 0; k < ctx.devValues.size(); ++k) {
        Measurement::DevSample s;
        s.value = ctx.devValues[k];
        s.gx = static_cast<int>(ctx.devCells[k] % static_cast<std::size_t>(gw));
        s.gy = static_cast<int>(ctx.devCells[k] / static_cast<std::size_t>(gw));
        m_devSamples.push_back(s);
    }
    const MeasureTools::Limits lim = MeasureTools::robustLimits(ctx.devValues, 3.0);
    m_devLo = lim.lo;
    m_devHi = lim.hi;
    m_devRobust = lim.robust;
    m_devClipped = static_cast<int>(lim.nClipped);
    m_devCoolWarm = ctx.devCoolWarm;
    m_footer = QStringLiteral("色标 %1 = [%2, %3] mm，裁剪 %4 点")
                   .arg(lim.robust ? QStringLiteral("中位数 ±3σ(MAD)")
                                   : QStringLiteral("1–99% 分位"))
                   .arg(fmt4(lim.lo)).arg(fmt4(lim.hi)).arg(lim.nClipped);

    m_cloudColors.reset();
    if (m_devColorBox && m_devColorBox->isChecked() && ctx.plane.valid
        && m_grid && m_gridW > 0 && m_gridH > 0) {
        std::vector<std::size_t> highlight = m_cells[0];
        highlight.insert(highlight.end(), m_cells[1].begin(), m_cells[1].end());
        m_cloudColors = std::make_shared<const std::vector<std::array<float, 3>>>(
            MeasureTools::cloudDeviationColors(*m_grid, m_gridW, m_gridH, ctx.plane,
                                               m_devLo, m_devHi, ctx.devCoolWarm,
                                               highlight));
    }
}

void MeasurePage::onRepeatAdd()
{
    if (!m_hasResult || m_primaryKey.isEmpty() || !m_series) {
        showHint(QStringLiteral("先执行一次测量，再把结果加入序列。"));
        return;
    }
    // 仅本次运行的累加器：刻意不落盘。
    (*m_series)[m_primaryKey].append(m_primaryValue);
    if (m_hint)
        m_hint->clear();
    refreshSeriesUi();
    if (m_seriesCombo) {
        const int idx = m_seriesCombo->findText(m_primaryKey);
        if (idx >= 0 && m_seriesCombo->currentIndex() != idx) {
            QSignalBlocker block(m_seriesCombo);   // 避免重入刷新
            m_seriesCombo->setCurrentIndex(idx);
        }
    }
    publish();
}

void MeasurePage::clearSeries()
{
    if (!m_series)
        return;
    m_series->clear();
    refreshSeriesUi();
    publish();
}

void MeasurePage::refreshSeriesUi()
{
    if (!m_seriesCombo)
        return;
    const QString keep = m_seriesCombo->currentText();
    {
        QSignalBlocker block(m_seriesCombo);
        m_seriesCombo->clear();
        if (m_series) {
            for (auto it = m_series->constBegin(); it != m_series->constEnd(); ++it) {
                if (!it.value().isEmpty())
                    m_seriesCombo->addItem(it.key());
            }
        }
        const int idx = m_seriesCombo->findText(keep);
        if (idx >= 0)
            m_seriesCombo->setCurrentIndex(idx);
    }
    if (!m_seriesSummary)
        return;
    const QString name = m_seriesCombo->currentText();
    if (name.isEmpty() || !m_series || !m_series->contains(name)) {
        m_seriesSummary->setText(QStringLiteral("—"));
        return;
    }
    const QVector<double>& vals = m_series->value(name);
    const MeasureTools::Repeatability rep =
        MeasureTools::repeatability(std::vector<double>(vals.begin(), vals.end()));
    m_seriesSummary->setText(
        rep.valid ? QStringLiteral("n=%1  均值 %2 mm  σ %3 mm  极差 %4 mm  ±3σ %5 mm")
                        .arg(rep.n).arg(fmt4(rep.mean)).arg(fmt4(rep.stdDev))
                        .arg(fmt4(rep.range)).arg(fmt4(3.0 * rep.stdDev))
                  : QStringLiteral("样本不足（n=%1）").arg(rep.n));
}

Measurement::Snapshot MeasurePage::snapshot() const
{
    Measurement::Snapshot s;
    s.valid = m_hasResult;
    s.title = QString::fromUtf8(m_spec.name);
    s.footer = m_footer;
    s.label = s.title;

    s.devSamples = m_devSamples;
    s.gridW = m_gridW;
    s.gridH = m_gridH;
    s.limitLo = m_devLo;
    s.limitHi = m_devHi;
    s.robustLimits = m_devRobust;
    s.clipped = m_devClipped;
    s.unit = QStringLiteral("mm");
    s.coolWarm = m_devCoolWarm;

    s.annotations = m_annotations;

    s.section = m_section;
    s.sectionStep = m_sectionStep;
    s.sectionPoints = static_cast<int>(m_section.size());

    // 运行图始终显示 combo 里选中的序列（也就是用户正在累积的那条）。
    if (m_seriesCombo && m_series) {
        const QString name = m_seriesCombo->currentText();
        if (!name.isEmpty() && m_series->contains(name)) {
            s.seriesName = name;
            s.series = m_series->value(name);
            const MeasureTools::Repeatability rep = MeasureTools::repeatability(
                std::vector<double>(s.series.begin(), s.series.end()));
            s.seriesN = static_cast<int>(rep.n);
            s.seriesMean = rep.mean;
            s.seriesSigma = rep.stdDev;
            s.seriesRange = rep.range;
        }
    }
    s.hasTolerance = m_tolEnable && m_tolEnable->isChecked();
    s.tolLo = m_tolLo ? m_tolLo->value() : 0.0;
    s.tolHi = m_tolHi ? m_tolHi->value() : 0.0;

    s.cloudColors = m_cloudColors;   // 引用计数，不拷贝元素
    s.hasCloudColors = m_cloudColors && !m_cloudColors->empty();
    s.hasPlane = m_hasPlane;
    s.planePoint = m_planePoint;
    s.planeNormal = m_planeNormal;
    s.hasRoiBox = m_hasBox;
    s.boxMin = m_boxMin;
    s.boxMax = m_boxMax;
    return s;
}

void MeasurePage::publish()
{
    emit snapshotReady(snapshot());
}
