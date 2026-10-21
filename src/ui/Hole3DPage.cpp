#include "ui/Hole3DPage.h"

#include <QAbstractButton>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QEvent>
#include <QFrame>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMouseEvent>
#include <QPainter>
#include <QPushButton>
#include <QScrollArea>
#include <QSignalBlocker>
#include <QStackedWidget>
#include <QStandardItemModel>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>
#include <limits>
#include <string>
#include <vector>

// ── 设计令牌（逐字来自 MyUIdesign/2.html）──────────────────────────────
namespace {

const char* kBlue = "#1890ff";
const char* kBlueHover = "#40a9ff";
const char* kGreen = "#52c41a";
const char* kRed = "#ff4d4f";
const char* kTextMain = "#1e293b";
const char* kTextSub = "#64748b";
const char* kTextMuted = "#94a3b8";

QString fromStd(const std::string& s)
{
    return QString::fromStdString(s);
}

void addRow(MeasureContext& ctx, const QString& label, const QString& value,
            const QString& unit, int points, const QString& confidence)
{
    ctx.rows.push_back({ label, value, unit, points, confidence });
}

// 2.html 的开关：40×22 的胶囊 + 14px 圆钮。QSS 做不出滑块位移，所以自绘。
class ToggleSwitch : public QAbstractButton {
public:
    explicit ToggleSwitch(QWidget* parent = nullptr)
        : QAbstractButton(parent)
    {
        setCheckable(true);
        setFixedSize(40, 22);
        setCursor(Qt::PointingHandCursor);
        connect(this, &QAbstractButton::toggled, this, [this](bool) { update(); });
    }

protected:
    void paintEvent(QPaintEvent*) override
    {
        QPainter p(this);
        p.setRenderHint(QPainter::Antialiasing);
        QColor track = isChecked() ? QColor(kBlue) : QColor("#cbd5e1");
        if (!isEnabled())
            track.setAlphaF(0.5);
        p.setPen(Qt::NoPen);
        p.setBrush(track);
        p.drawRoundedRect(QRectF(0, 0, 40, 22), 11, 11);
        p.setBrush(QColor("#ffffff"));
        const qreal x = isChecked() ? 22.0 : 4.0;
        p.drawEllipse(QRectF(x, 4, 14, 14));
    }
};

QFrame* makeCard(QWidget* parent)
{
    auto* card = new QFrame(parent);
    card->setObjectName(QStringLiteral("hole3dCard"));
    auto* v = new QVBoxLayout(card);
    v->setContentsMargins(20, 18, 20, 20);
    v->setSpacing(16);
    return card;
}

QWidget* makeCardTitle(const QString& text, QWidget* parent)
{
    auto* row = new QWidget(parent);
    auto* h = new QHBoxLayout(row);
    h->setContentsMargins(0, 0, 0, 0);
    h->setSpacing(10);
    auto* bar = new QFrame(row);
    bar->setFixedSize(4, 16);
    bar->setStyleSheet(QStringLiteral("background:%1; border:none; border-radius:2px;")
                           .arg(kBlue));
    auto* label = new QLabel(text, row);
    label->setObjectName(QStringLiteral("hole3dCardTitle"));
    h->addWidget(bar);
    h->addWidget(label);
    h->addStretch();
    return row;
}

QLabel* makeSmallLabel(const QString& text, QWidget* parent, const char* objectName)
{
    auto* label = new QLabel(text, parent);
    label->setObjectName(QString::fromUtf8(objectName));
    label->setWordWrap(true);
    return label;
}

QWidget* makeFormRow(const QString& label, QWidget* field, QWidget* parent)
{
    auto* row = new QWidget(parent);
    auto* h = new QHBoxLayout(row);
    h->setContentsMargins(0, 0, 0, 0);
    h->setSpacing(12);
    auto* name = new QLabel(label, row);
    name->setObjectName(QStringLiteral("hole3dFormLabel"));
    name->setFixedWidth(100);
    h->addWidget(name);
    h->addWidget(field, 1);
    return row;
}

QComboBox* makeChoice(QWidget* parent, const QStringList& items, int current)
{
    auto* combo = new QComboBox(parent);
    combo->setObjectName(QStringLiteral("hole3dSelect"));
    combo->addItems(items);
    combo->setCurrentIndex(current);
    return combo;
}

QDoubleSpinBox* makeSpin(QWidget* parent, double value, double lo, double hi)
{
    auto* spin = new QDoubleSpinBox(parent);
    spin->setObjectName(QStringLiteral("hole3dSpin"));
    spin->setDecimals(4);
    spin->setRange(lo, hi);
    spin->setSingleStep(0.01);
    spin->setValue(value);
    spin->setAlignment(Qt::AlignCenter);
    spin->setButtonSymbols(QAbstractSpinBox::NoButtons);
    return spin;
}

QLineEdit* makeCoord(QWidget* parent)
{
    auto* edit = new QLineEdit(QStringLiteral("0.00"), parent);
    edit->setObjectName(QStringLiteral("hole3dInput"));
    edit->setReadOnly(true);
    edit->setAlignment(Qt::AlignCenter);
    return edit;
}

// 三个坐标输入（X / Y / Z）的 3 列网格。
QWidget* makeCoordGrid(QLineEdit* (&edits)[3], QWidget* parent)
{
    auto* box = new QWidget(parent);
    auto* grid = new QGridLayout(box);
    grid->setContentsMargins(0, 0, 0, 0);
    grid->setHorizontalSpacing(10);
    grid->setVerticalSpacing(5);
    const char* names[3] = { "X", "Y", "Z" };
    for (int i = 0; i < 3; ++i) {
        auto* caption = new QLabel(QString::fromUtf8(names[i]), box);
        caption->setObjectName(QStringLiteral("hole3dCoordLabel"));
        caption->setAlignment(Qt::AlignCenter);
        edits[i] = makeCoord(box);
        grid->addWidget(caption, 0, i);
        grid->addWidget(edits[i], 1, i);
    }
    return box;
}

QFrame* makeTolBox(const QString& label, QDoubleSpinBox*& spin, QWidget* parent)
{
    auto* box = new QFrame(parent);
    box->setObjectName(QStringLiteral("hole3dTolBox"));
    auto* v = new QVBoxLayout(box);
    v->setContentsMargins(12, 10, 12, 10);
    v->setSpacing(8);
    auto* caption = new QLabel(label, box);
    caption->setObjectName(QStringLiteral("hole3dStatLabel"));
    caption->setAlignment(Qt::AlignCenter);
    v->addWidget(caption);
    spin = makeSpin(box, 0.0, -1.0e6, 1.0e6);
    v->addWidget(spin);
    return box;
}

QFrame* makeStatBox(const QString& label, QLabel*& value, QWidget* parent)
{
    auto* box = new QFrame(parent);
    box->setObjectName(QStringLiteral("hole3dStatBox"));
    auto* v = new QVBoxLayout(box);
    v->setContentsMargins(10, 10, 10, 10);
    v->setSpacing(6);
    auto* caption = new QLabel(label, box);
    caption->setObjectName(QStringLiteral("hole3dStatLabel"));
    caption->setAlignment(Qt::AlignCenter);
    v->addWidget(caption);
    value = new QLabel(QStringLiteral("--"), box);
    value->setObjectName(QStringLiteral("hole3dStatValue"));
    value->setAlignment(Qt::AlignCenter);
    v->addWidget(value);
    return box;
}

} // namespace

Hole3DPage::Hole3DPage(QWidget* parent)
    : MeasurePage(MeasureTools::Method::Hole3D, false, parent)
{
    setObjectName(QStringLiteral("hole3dPage"));
    buildUi();
    connect(this, &MeasurePage::roiChanged, this, &Hole3DPage::refreshRoiDisplay);
    refreshRoiDisplay();
    updateResultDisplay();
    updateSequenceUi();
}

void Hole3DPage::buildUi()
{
    setStyleSheet(QStringLiteral(
        "QWidget#hole3dPage { background:#f4f6f8; }"
        "QFrame#hole3dBar { background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; }"
        "QLabel#hole3dTitle { font-size:18px; font-weight:bold; color:#1e293b;"
        " background:transparent; border:none; }"
        "QLabel#hole3dIcon { font-size:18px; color:#1890ff; background:transparent;"
        " border:none; }"
        "QPushButton#hole3dTab { border:none; border-bottom:3px solid transparent;"
        " background:transparent; color:#64748b; font-size:15px; font-weight:bold;"
        " padding:18px 12px 14px 12px; }"
        "QPushButton#hole3dTab:hover { color:#1890ff; }"
        "QPushButton#hole3dTab:checked { color:#1890ff; border-bottom-color:#1890ff; }"
        "QFrame#hole3dCard { background:#ffffff; border:1px solid #e2e8f0;"
        " border-radius:8px; }"
        "QLabel#hole3dCardTitle { font-size:15px; font-weight:bold; color:#1e293b;"
        " background:transparent; border:none; }"
        "QLabel#hole3dFormLabel { font-size:14px; color:#64748b; font-weight:500;"
        " background:transparent; border:none; }"
        "QLabel#hole3dCoordLabel { font-size:12px; color:#64748b; background:transparent;"
        " border:none; }"
        "QLabel#hole3dSmall { font-size:12px; color:#64748b; background:transparent;"
        " border:none; }"
        "QLabel#hole3dNote { font-size:12px; color:#94a3b8; background:transparent;"
        " border:none; }"
        "QLineEdit#hole3dInput, QComboBox#hole3dSelect, QDoubleSpinBox#hole3dSpin {"
        " background:#ffffff; border:1px solid #e2e8f0; border-radius:6px;"
        " min-height:36px; padding:0 10px; font-size:14px; color:#1e293b; }"
        "QLineEdit#hole3dInput[readOnly=\"true\"] { background:#f8fafc;"
        " font-family:Consolas,\"Courier New\",monospace; }"
        "QComboBox#hole3dSelect:disabled, QDoubleSpinBox#hole3dSpin:disabled {"
        " background:#f8fafc; color:#94a3b8; }"
        "QComboBox#hole3dSelect::drop-down { border:none; width:24px; }"
        "QComboBox#hole3dSelect QAbstractItemView { background:#ffffff;"
        " border:1px solid #e2e8f0; selection-background-color:#e6f4ff;"
        " selection-color:#1e293b; }"
        "QDoubleSpinBox#hole3dSpin { font-family:Consolas,\"Courier New\",monospace; }"
        "QFrame#hole3dTolBox { background:#f8fafc; border:1px solid #e2e8f0;"
        " border-radius:6px; }"
        "QFrame#hole3dStatBox { background:#f8fafc; border:1px solid #e2e8f0;"
        " border-radius:6px; }"
        "QLabel#hole3dStatLabel { font-size:12px; color:#64748b; background:transparent;"
        " border:none; }"
        "QLabel#hole3dStatValue { font-size:18px; font-weight:bold;"
        " font-family:Consolas,\"Courier New\",monospace; color:#1e293b;"
        " background:transparent; border:none; }"
        "QFrame#hole3dResultPanel, QFrame#hole3dStatsPanel { background:#ffffff;"
        " border:1px solid #e2e8f0; border-radius:10px; }"
        "QLabel#hole3dResultTitle { font-size:15px; color:#64748b; background:transparent;"
        " border:none; }"
        "QLabel#hole3dResultValue { font-size:46px; font-weight:bold;"
        " font-family:Consolas,\"Courier New\",monospace; color:#1890ff;"
        " background:transparent; border:none; }"
        "QLabel#hole3dResultUnit { font-size:20px; color:#64748b; background:transparent;"
        " border:none; }"
        "QLabel#hole3dResultDetail { font-size:12px; color:#64748b;"
        " background:transparent; border:none; }"
        "QLabel#hole3dPanelTitle { font-size:15px; font-weight:bold; color:#1e293b;"
        " background:transparent; border:none; }"
        "QLabel#hole3dCount { font-size:12px; color:#64748b; background:#f1f5f9;"
        " border:none; border-radius:10px; padding:3px 10px; }"
        "QLabel#hole3dTag { font-size:14px; font-weight:bold; color:#ffffff;"
        " background:#e2e8f0; border:none; border-radius:14px; padding:6px 22px; }"
        "QPushButton#hole3dBtnOutline { background:#ffffff; border:1px solid #e2e8f0;"
        " border-radius:6px; padding:8px 22px; font-size:14px; font-weight:bold;"
        " color:#1e293b; }"
        "QPushButton#hole3dBtnOutline:hover { border-color:#1890ff; color:#1890ff; }"
        "QPushButton#hole3dBtnPrimary { background:#1890ff; border:1px solid #1890ff;"
        " border-radius:6px; padding:8px 22px; font-size:14px; font-weight:bold;"
        " color:#ffffff; }"
        "QPushButton#hole3dBtnPrimary:hover { background:#40a9ff; border-color:#40a9ff; }"
        "QPushButton#hole3dBtnSuccess { background:#52c41a; border:1px solid #52c41a;"
        " border-radius:6px; padding:8px 22px; font-size:14px; font-weight:bold;"
        " color:#ffffff; }"
        "QPushButton#hole3dBtnSuccess:hover:enabled { background:#73d13d;"
        " border-color:#73d13d; }"
        "QPushButton#hole3dBtnSuccess:disabled { background:#cbd5e1;"
        " border-color:#cbd5e1; color:#ffffff; }"
        "QScrollArea { background:transparent; border:none; }"
        "QFrame#hole3dTabContent { background:transparent; border:none; }"
        "QScrollArea#hole3dHistory { background:#ffffff; border:1px solid #e2e8f0;"
        " border-radius:6px; }"
        "QFrame#hole3dHistoryHost { background:#ffffff; border:none; }"
        "QLabel#hole3dHistoryEmpty { font-size:12px; color:#94a3b8;"
        " background:transparent; border:none; }"
        "QLabel#hole3dHistoryName { font-size:13px; color:#64748b;"
        " background:transparent; border:none; }"
        "QLabel#hole3dHistoryValue { font-size:13px; font-weight:bold;"
        " font-family:Consolas,\"Courier New\",monospace; color:#1e293b;"
        " background:transparent; border:none; }"));

    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(12, 12, 12, 12);
    root->setSpacing(12);
    root->addWidget(buildHeader());
    root->addWidget(m_tabs, 1);
    root->addWidget(buildFooter());
}

QWidget* Hole3DPage::buildHeader()
{
    auto* header = new QFrame(this);
    header->setObjectName(QStringLiteral("hole3dBar"));
    auto* h = new QHBoxLayout(header);
    h->setContentsMargins(20, 0, 20, 0);
    h->setSpacing(10);

    auto* titleBox = new QWidget(header);
    auto* th = new QHBoxLayout(titleBox);
    th->setContentsMargins(0, 0, 0, 0);
    th->setSpacing(10);
    auto* icon = new QLabel(QStringLiteral("⭕"), titleBox);
    icon->setObjectName(QStringLiteral("hole3dIcon"));
    auto* title = new QLabel(QStringLiteral("3D 孔洞测量"), titleBox);
    title->setObjectName(QStringLiteral("hole3dTitle"));
    th->addWidget(icon);
    th->addWidget(title);
    th->addStretch();
    h->addWidget(titleBox);
    h->addStretch();

    m_tabParams = new QPushButton(QStringLiteral("1. 参数配置"), header);
    m_tabParams->setObjectName(QStringLiteral("hole3dTab"));
    m_tabParams->setCheckable(true);
    m_tabParams->setChecked(true);
    m_tabParams->setCursor(Qt::PointingHandCursor);
    m_tabResults = new QPushButton(QStringLiteral("2. 测试与结果"), header);
    m_tabResults->setObjectName(QStringLiteral("hole3dTab"));
    m_tabResults->setCheckable(true);
    m_tabResults->setCursor(Qt::PointingHandCursor);
    h->addWidget(m_tabParams);
    h->addWidget(m_tabResults);

    connect(m_tabParams, &QPushButton::clicked, this, [this]() { switchTab(0); });
    connect(m_tabResults, &QPushButton::clicked, this, [this]() { switchTab(1); });

    // 两个页签各带一个滚动区：结果页不会因为参数页更高而空出一大片。
    m_tabs = new QStackedWidget(this);

    auto* paramsScroll = new QScrollArea(m_tabs);
    paramsScroll->setWidgetResizable(true);
    paramsScroll->setFrameShape(QFrame::NoFrame);
    paramsScroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    paramsScroll->setWidget(buildParamsTab());
    paramsScroll->viewport()->setAutoFillBackground(false);
    m_tabs->addWidget(paramsScroll);

    auto* resultsScroll = new QScrollArea(m_tabs);
    resultsScroll->setWidgetResizable(true);
    resultsScroll->setFrameShape(QFrame::NoFrame);
    resultsScroll->setWidget(buildResultsTab());
    resultsScroll->viewport()->setAutoFillBackground(false);
    m_tabs->addWidget(resultsScroll);

    return header;
}

QWidget* Hole3DPage::buildParamsTab()
{
    auto* content = new QFrame;
    content->setObjectName(QStringLiteral("hole3dTabContent"));
    auto* v = new QVBoxLayout(content);
    v->setContentsMargins(0, 2, 2, 2);
    v->setSpacing(15);

    // ── 1. 探测位置边界 ──
    QFrame* position = makeCard(content);
    auto* pl = qobject_cast<QVBoxLayout*>(position->layout());
    pl->addWidget(makeCardTitle(QStringLiteral("探测位置边界"), position));

    m_source = makeChoice(position,
                          { QStringLiteral("边界框"), QStringLiteral("圆形 ROI"),
                            QStringLiteral("矩形 ROI") },
                          2);
    if (auto* model = qobject_cast<QStandardItemModel*>(m_source->model())) {
        for (int i = 0; i < 2; ++i)
            if (QStandardItem* item = model->item(i))
                item->setEnabled(false);
    }
    m_source->setToolTip(QStringLiteral("当前版本只支持在 2D 视图上拖矩形 ROI"));
    pl->addWidget(makeFormRow(QStringLiteral("数据来源"), m_source, position));

    auto* coords = new QWidget(position);
    auto* ch = new QHBoxLayout(coords);
    ch->setContentsMargins(0, 0, 0, 0);
    ch->setSpacing(20);
    auto* startBox = new QWidget(coords);
    auto* sv = new QVBoxLayout(startBox);
    sv->setContentsMargins(0, 0, 0, 0);
    sv->setSpacing(8);
    sv->addWidget(makeSmallLabel(QStringLiteral("起点 (Start)"), startBox, "hole3dSmall"));
    sv->addWidget(makeCoordGrid(m_start, startBox));
    auto* endBox = new QWidget(coords);
    auto* ev = new QVBoxLayout(endBox);
    ev->setContentsMargins(0, 0, 0, 0);
    ev->setSpacing(8);
    ev->addWidget(makeSmallLabel(QStringLiteral("终点 (End)"), endBox, "hole3dSmall"));
    ev->addWidget(makeCoordGrid(m_end, endBox));
    ch->addWidget(startBox, 1);
    ch->addWidget(endBox, 1);
    pl->addWidget(coords);

    m_roiState = makeSmallLabel(QString(), position, "hole3dNote");
    m_roiState->setText(QStringLiteral("未选择 — 在 2D 视图上按住左键拖框（只需 ROI A）"));
    pl->addWidget(m_roiState);
    pl->addWidget(makeSmallLabel(
        QStringLiteral("起点 / 终点是框内点云的三维范围；数据来源与右图 ROI 同步。"),
        position, "hole3dNote"));
    v->addWidget(position);

    // ── 2. 基础探测设置 ──
    QFrame* basics = makeCard(content);
    auto* bl = qobject_cast<QVBoxLayout*>(basics->layout());
    bl->addWidget(makeCardTitle(QStringLiteral("基础探测设置"), basics));

    m_mode = makeChoice(basics,
                        { QStringLiteral("探测单个圆孔"), QStringLiteral("探测多个圆孔"),
                          QStringLiteral("探测单个方孔"), QStringLiteral("探测多个方孔"),
                          QStringLiteral("探测方孔和圆孔") },
                        0);
    if (auto* model = qobject_cast<QStandardItemModel*>(m_mode->model())) {
        for (int i = 1; i < m_mode->count(); ++i)
            if (QStandardItem* item = model->item(i))
                item->setEnabled(false);
    }
    m_mode->setToolTip(QStringLiteral("当前版本只支持单个圆孔"));
    bl->addWidget(makeFormRow(QStringLiteral("操作模式"), m_mode, basics));

    m_direction = makeChoice(basics,
                             { QStringLiteral("从内向外探测 (查找孔洞)"),
                               QStringLiteral("从外向内探测 (查找凸起)") },
                             0);
    m_direction->setToolTip(
        QStringLiteral("从内向外 = 找孔壁内缘；从外向内 = 找材料外缘 / 凸起"));
    bl->addWidget(makeFormRow(QStringLiteral("探测方向"), m_direction, basics));

    m_geometry = makeChoice(basics,
                            { QStringLiteral("半径大小"), QStringLiteral("圆心坐标"),
                              QStringLiteral("半径和圆心坐标") },
                            2);
    bl->addWidget(makeFormRow(QStringLiteral("输出几何"), m_geometry, basics));

    auto* angleRow = new QWidget(basics);
    auto* ah = new QHBoxLayout(angleRow);
    ah->setContentsMargins(0, 0, 0, 0);
    ah->setSpacing(8);
    m_angle = makeSpin(angleRow, 45.0, 0.0, 360.0);
    m_angle->setDecimals(2);
    m_angle->setEnabled(false);
    auto* degree = new QLabel(QStringLiteral("°"), angleRow);
    degree->setObjectName(QStringLiteral("hole3dSmall"));
    ah->addWidget(m_angle);
    ah->addWidget(degree);
    ah->addStretch();
    bl->addWidget(makeFormRow(QStringLiteral("探测角度"), angleRow, basics));
    bl->addWidget(makeSmallLabel(
        QStringLiteral("当前版本固定 360° 扫描单个圆孔；探测角度为后续多孔 / 扇形扫描预留。"),
        basics, "hole3dNote"));
    v->addWidget(basics);

    // ── 3. 高级选项与滤波（默认折叠）──
    QFrame* advanced = new QFrame(content);
    advanced->setObjectName(QStringLiteral("hole3dCard"));
    auto* av = new QVBoxLayout(advanced);
    av->setContentsMargins(0, 0, 0, 0);
    av->setSpacing(0);

    m_advancedHeader = new QWidget(advanced);
    m_advancedHeader->setCursor(Qt::PointingHandCursor);
    auto* hh = new QHBoxLayout(m_advancedHeader);
    hh->setContentsMargins(20, 16, 20, 16);
    hh->setSpacing(10);
    auto* bar = new QFrame(m_advancedHeader);
    bar->setFixedSize(4, 16);
    bar->setStyleSheet(QStringLiteral("background:%1; border:none; border-radius:2px;")
                           .arg(kBlue));
    auto* headerTitle = new QLabel(QStringLiteral("高级选项与滤波"), m_advancedHeader);
    headerTitle->setObjectName(QStringLiteral("hole3dCardTitle"));
    m_advancedArrow = new QLabel(QStringLiteral("▼"), m_advancedHeader);
    m_advancedArrow->setObjectName(QStringLiteral("hole3dNote"));
    hh->addWidget(bar);
    hh->addWidget(headerTitle);
    hh->addStretch();
    hh->addWidget(m_advancedArrow);
    m_advancedHeader->installEventFilter(this);
    av->addWidget(m_advancedHeader);

    m_advancedBody = new QWidget(advanced);
    auto* ab = new QVBoxLayout(m_advancedBody);
    ab->setContentsMargins(20, 0, 20, 20);
    ab->setSpacing(12);

    auto* filterRow = new QFrame(m_advancedBody);
    filterRow->setObjectName(QStringLiteral("hole3dTolBox"));
    auto* fh = new QHBoxLayout(filterRow);
    fh->setContentsMargins(12, 10, 12, 10);
    fh->setSpacing(12);
    auto* filterSwitch = new ToggleSwitch(filterRow);
    filterSwitch->setChecked(true);
    filterSwitch->setEnabled(false);
    auto* filterLabel = new QLabel(QStringLiteral("启用离群点移除"), filterRow);
    filterLabel->setObjectName(QStringLiteral("hole3dFormLabel"));
    auto* sigma = makeSpin(filterRow, 2.0, 0.0, 10.0);
    sigma->setEnabled(false);
    sigma->setFixedWidth(110);
    auto* sigmaUnit = new QLabel(QStringLiteral("标准差"), filterRow);
    sigmaUnit->setObjectName(QStringLiteral("hole3dSmall"));
    fh->addWidget(filterSwitch);
    fh->addWidget(filterLabel);
    fh->addStretch();
    fh->addWidget(sigma);
    fh->addWidget(sigmaUnit);
    ab->addWidget(filterRow);

    auto* devRow = new QFrame(m_advancedBody);
    devRow->setObjectName(QStringLiteral("hole3dTolBox"));
    auto* dh = new QHBoxLayout(devRow);
    dh->setContentsMargins(12, 10, 12, 10);
    dh->setSpacing(12);
    m_devColor = new ToggleSwitch(devRow);
    auto* devLabel = new QLabel(
        QStringLiteral("3D 偏差着色（在 3D 视窗同步显示测量区域）"), devRow);
    devLabel->setObjectName(QStringLiteral("hole3dFormLabel"));
    dh->addWidget(m_devColor);
    dh->addWidget(devLabel);
    dh->addStretch();
    ab->addWidget(devRow);
    ab->addWidget(makeSmallLabel(
        QStringLiteral("边界圆拟合内部已按 MAD 剔除粗大点，离群点滤波暂不可调。"),
        m_advancedBody, "hole3dNote"));

    m_advancedBody->setVisible(false);
    av->addWidget(m_advancedBody);
    v->addWidget(advanced);

    // ── 4. 公差评价 ──
    QFrame* tolerance = makeCard(content);
    auto* tl = qobject_cast<QVBoxLayout*>(tolerance->layout());
    tl->addWidget(makeCardTitle(QStringLiteral("公差评价"), tolerance));
    auto* tol = new QWidget(tolerance);
    auto* th = new QHBoxLayout(tol);
    th->setContentsMargins(0, 0, 0, 0);
    th->setSpacing(15);
    auto* loBox = makeTolBox(QStringLiteral("下限偏移 (-)"), m_tolLoOff, tol);
    auto* nomBox = makeTolBox(QStringLiteral("标称值"), m_tolNominal, tol);
    auto* hiBox = makeTolBox(QStringLiteral("上限偏移 (+)"), m_tolHiOff, tol);
    m_tolLoOff->setValue(-0.05);
    m_tolNominal->setValue(10.0);
    m_tolHiOff->setValue(0.05);
    th->addWidget(loBox, 1);
    th->addWidget(nomBox, 1);
    th->addWidget(hiBox, 1);
    tl->addWidget(tol);
    tl->addWidget(makeSmallLabel(
        QStringLiteral("合格区间 = 标称值 + 下限偏移 … 标称值 + 上限偏移（判定用「直径」）。"),
        tolerance, "hole3dNote"));
    v->addWidget(tolerance);

    v->addStretch();

    connect(m_direction, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int) { updateGeometryDetail(); });
    connect(m_geometry, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int) { updateGeometryDetail(); });
    for (QDoubleSpinBox* spin : { m_tolLoOff, m_tolNominal, m_tolHiOff })
        connect(spin, QOverload<double>::of(&QDoubleSpinBox::valueChanged),
                this, [this](double) { applyTolerance(); });
    connect(m_devColor, &QAbstractButton::toggled, this, [this](bool on) {
        emit deviationColoringChanged(on);
        rerun();
    });

    return content;
}

QWidget* Hole3DPage::buildResultsTab()
{
    auto* content = new QFrame;
    content->setObjectName(QStringLiteral("hole3dTabContent"));
    auto* v = new QVBoxLayout(content);
    v->setContentsMargins(0, 2, 2, 2);
    v->setSpacing(0);

    auto* dashboard = new QWidget(content);
    auto* dh = new QHBoxLayout(dashboard);
    dh->setContentsMargins(0, 0, 0, 0);
    dh->setSpacing(20);

    // ── 当前测量结果 ──
    auto* result = new QFrame(dashboard);
    result->setObjectName(QStringLiteral("hole3dResultPanel"));
    result->setMinimumHeight(270);
    auto* rv = new QVBoxLayout(result);
    rv->setContentsMargins(20, 20, 20, 20);
    rv->setSpacing(0);
    rv->addStretch();
    m_resultTitle = new QLabel(QStringLiteral("当前测量结果"), result);
    m_resultTitle->setObjectName(QStringLiteral("hole3dResultTitle"));
    m_resultTitle->setAlignment(Qt::AlignCenter);
    rv->addWidget(m_resultTitle);
    rv->addSpacing(14);

    auto* valueRow = new QWidget(result);
    auto* vh = new QHBoxLayout(valueRow);
    vh->setContentsMargins(0, 0, 0, 0);
    vh->setSpacing(8);
    m_resultValue = new QLabel(QStringLiteral("--"), valueRow);
    m_resultValue->setObjectName(QStringLiteral("hole3dResultValue"));
    m_resultUnit = new QLabel(QStringLiteral("mm"), valueRow);
    m_resultUnit->setObjectName(QStringLiteral("hole3dResultUnit"));
    vh->addStretch();
    vh->addWidget(m_resultValue);
    vh->addWidget(m_resultUnit, 0, Qt::AlignBottom);
    vh->addStretch();
    rv->addWidget(valueRow);
    rv->addSpacing(8);

    m_resultDetail = new QLabel(QString(), result);
    m_resultDetail->setObjectName(QStringLiteral("hole3dResultDetail"));
    m_resultDetail->setAlignment(Qt::AlignCenter);
    m_resultDetail->setWordWrap(true);
    rv->addWidget(m_resultDetail);
    rv->addSpacing(16);

    auto* tagRow = new QWidget(result);
    auto* gh = new QHBoxLayout(tagRow);
    gh->setContentsMargins(0, 0, 0, 0);
    m_resultTag = new QLabel(QStringLiteral("等待测量"), tagRow);
    m_resultTag->setObjectName(QStringLiteral("hole3dTag"));
    m_resultTag->setAlignment(Qt::AlignCenter);
    gh->addStretch();
    gh->addWidget(m_resultTag);
    gh->addStretch();
    rv->addWidget(tagRow);
    rv->addStretch();
    dh->addWidget(result, 1);

    // ── 重复性统计 ──
    auto* stats = new QFrame(dashboard);
    stats->setObjectName(QStringLiteral("hole3dStatsPanel"));
    stats->setMinimumHeight(270);
    auto* sv = new QVBoxLayout(stats);
    sv->setContentsMargins(20, 18, 20, 18);
    sv->setSpacing(12);

    auto* sh = new QHBoxLayout();
    sh->setContentsMargins(0, 0, 0, 0);
    auto* statsTitle = new QLabel(QStringLiteral("重复性统计"), stats);
    statsTitle->setObjectName(QStringLiteral("hole3dPanelTitle"));
    m_seqCount = new QLabel(QStringLiteral("0 组数据"), stats);
    m_seqCount->setObjectName(QStringLiteral("hole3dCount"));
    sh->addWidget(statsTitle);
    sh->addStretch();
    sh->addWidget(m_seqCount);
    sv->addLayout(sh);

    auto* grid = new QGridLayout();
    grid->setContentsMargins(0, 0, 0, 0);
    grid->setHorizontalSpacing(12);
    grid->setVerticalSpacing(12);
    grid->addWidget(makeStatBox(QStringLiteral("最大值"), m_statMax, stats), 0, 0);
    grid->addWidget(makeStatBox(QStringLiteral("最小值"), m_statMin, stats), 0, 1);
    grid->addWidget(makeStatBox(QStringLiteral("平均值"), m_statAvg, stats), 1, 0);
    grid->addWidget(makeStatBox(QStringLiteral("极差"), m_statRange, stats), 1, 1);
    sv->addLayout(grid);

    auto* history = new QScrollArea(stats);
    history->setObjectName(QStringLiteral("hole3dHistory"));
    history->setWidgetResizable(true);
    history->setFrameShape(QFrame::NoFrame);
    history->setMinimumHeight(92);
    history->setMaximumHeight(130);
    m_historyHost = new QFrame;
    m_historyHost->setObjectName(QStringLiteral("hole3dHistoryHost"));
    m_historyLayout = new QVBoxLayout(m_historyHost);
    m_historyLayout->setContentsMargins(10, 4, 10, 4);
    m_historyLayout->setSpacing(0);
    m_historyLayout->addStretch();
    history->setWidget(m_historyHost);
    sv->addWidget(history, 1);
    dh->addWidget(stats, 1);

    // 卡片按内容高度排布（与 2.html 一致）；多出来的高度留在下方，
    // 不拉伸统计面板（拉长会把这个「N 组数据」小胶囊也拉成一条竖条）。
    v->addWidget(dashboard);
    v->addStretch();
    return content;
}

QWidget* Hole3DPage::buildFooter()
{
    auto* footer = new QFrame(this);
    footer->setObjectName(QStringLiteral("hole3dBar"));
    auto* h = new QHBoxLayout(footer);
    h->setContentsMargins(20, 12, 20, 12);
    h->setSpacing(12);

    auto* cancel = new QPushButton(QStringLiteral("取消"), footer);
    cancel->setObjectName(QStringLiteral("hole3dBtnOutline"));
    cancel->setCursor(Qt::PointingHandCursor);
    h->addWidget(cancel);

    m_hint = new QLabel(footer);
    m_hint->setObjectName(QStringLiteral("hole3dHint"));
    m_hint->setWordWrap(true);
    m_hint->setMinimumWidth(0);
    m_hint->setStyleSheet(QStringLiteral("color:%1; font-size:12px; border:none;")
                              .arg(kTextSub));
    h->addWidget(m_hint, 1);

    auto* measure = new QPushButton(QStringLiteral("▶ 开始测量"), footer);
    measure->setObjectName(QStringLiteral("hole3dBtnPrimary"));
    measure->setCursor(Qt::PointingHandCursor);
    h->addWidget(measure);

    m_addButton = new QPushButton(QStringLiteral("➕ 添加到序列"), footer);
    m_addButton->setObjectName(QStringLiteral("hole3dBtnSuccess"));
    m_addButton->setCursor(Qt::PointingHandCursor);
    m_addButton->setEnabled(false);
    h->addWidget(m_addButton);

    connect(cancel, &QPushButton::clicked, this, &Hole3DPage::onCancel);
    connect(measure, &QPushButton::clicked, this, &Hole3DPage::onMeasure);
    connect(m_addButton, &QPushButton::clicked, this, &Hole3DPage::onAddToSequence);
    return footer;
}

void Hole3DPage::switchTab(int index)
{
    if (!m_tabs)
        return;
    m_tabs->setCurrentIndex(index);
    m_tabParams->setChecked(index == 0);
    m_tabResults->setChecked(index != 0);
}

bool Hole3DPage::eventFilter(QObject* watched, QEvent* event)
{
    if (watched == m_advancedHeader && event->type() == QEvent::MouseButtonRelease) {
        auto* me = static_cast<QMouseEvent*>(event);
        if (me->button() == Qt::LeftButton) {
            toggleAdvanced();
            return true;
        }
    }
    return MeasurePage::eventFilter(watched, event);
}

void Hole3DPage::toggleAdvanced()
{
    if (!m_advancedBody)
        return;
    const bool show = !m_advancedBody->isVisible();
    m_advancedBody->setVisible(show);
    m_advancedArrow->setText(show ? QStringLiteral("▲") : QStringLiteral("▼"));
}

bool Hole3DPage::materialInside() const
{
    return m_direction && m_direction->currentIndex() == 1;
}

double Hole3DPage::toleranceLo() const
{
    return m_tolNominal->value() + m_tolLoOff->value();
}

double Hole3DPage::toleranceHi() const
{
    return m_tolNominal->value() + m_tolHiOff->value();
}

void Hole3DPage::compute(MeasureContext& ctx)
{
    const std::vector<MeasureTools::Vec3>& pts = ctx.roi[0];
    if (pts.size() < 8) {
        ctx.refusal = QStringLiteral(
                          "3D 孔洞需要在 ROI A 内至少 8 个点（孔/外缘 + 外圈约 2 个点距"
                          "的材料），当前 %1 个。")
                          .arg(static_cast<qulonglong>(pts.size()));
        return;
    }

    const bool inside = materialInside();
    const std::vector<double> noGrid;
    const std::vector<double>& gridRef = ctx.grid ? *ctx.grid : noGrid;
    const MeasureTools::BoundaryCircle bc = MeasureTools::measureBoundaryCircle(
        pts, ctx.roiCells[0], ctx.gridW, ctx.gridH, gridRef,
        ctx.image ? ctx.image->width : 0, ctx.image ? ctx.image->height : 0,
        ctx.image ? *ctx.image : MeasureTools::GrayImage{}, inside);
    if (!bc.valid) {
        ctx.refusal = fromStd(bc.message);
        return;
    }

    const int used = bc.used > 0 ? bc.used : bc.sectors;
    // 边缘样本不足时直接标「参考」——与合并前两个工具承诺的降级口径一致。
    const QString conf = bc.reliable ? confidenceFor(used, bc.rms)
                                     : QStringLiteral("参考");
    const QString edge = inside ? QStringLiteral("外缘") : QStringLiteral("孔");

    addRow(ctx, edge + QStringLiteral("直径"), fmt4(bc.diameter), QStringLiteral("mm"),
           used, conf);
    addRow(ctx, edge + QStringLiteral("半径"), fmt4(bc.radius), QStringLiteral("mm"),
           used, conf);
    addRow(ctx, edge + QStringLiteral("圆心"),
           QStringLiteral("(%1, %2, %3)")
               .arg(fmt4(bc.center[0]), fmt4(bc.center[1]), fmt4(bc.center[2])),
           QStringLiteral("mm"), used, conf);
    addRow(ctx, edge + QStringLiteral("圆度(半径极差)"), fmt4(bc.roundness),
           QStringLiteral("mm"), used, conf);
    addRow(ctx, QStringLiteral("扇区覆盖"),
           QStringLiteral("%1/%2").arg(used).arg(bc.sectors), QString(), used, conf);

    ctx.primaryKey = edge + QStringLiteral("直径");
    ctx.primaryValue = bc.diameter;
    ctx.hasPrimary = true;

    // 偏差图 = 到拟合圆的半径残差（turbo，与合并前两个工具同一套视觉）。
    std::vector<double> radial(pts.size());
    for (std::size_t k = 0; k < pts.size(); ++k) {
        const double dx = pts[k][0] - bc.center[0];
        const double dy = pts[k][1] - bc.center[1];
        const double dz = pts[k][2] - bc.center[2];
        radial[k] = std::sqrt(dx * dx + dy * dy + dz * dz) - bc.radius;
    }
    ctx.hasDeviation = true;
    ctx.devValues = radial;
    ctx.devCells = ctx.roiCells[0];
    ctx.devCoolWarm = false;

    const QRect r = ctx.roiRects->value(0);
    ctx.annotations.push_back({ QStringLiteral("⌀%1 mm").arg(fmt4(bc.diameter)),
                                QPoint(r.center().x(), r.center().y()), false });
    ctx.hasPlane = true;
    ctx.planePoint = bc.center;
    ctx.planeNormal = bc.normal;

    ctx.footer = bc.subpixel
        ? QStringLiteral("图像亚像素边界 %1 条，局部尺度 %2 mm/px")
              .arg(bc.used).arg(fmt4(bc.mmPerPx))
        : QStringLiteral("图像不可用，本结果为 3D 边界（粗）");
    ctx.confidenceNote = QStringLiteral("%1（%2）：亚像素边缘 %3/%4 条（覆盖 %5%%），"
                                        "圆度 %6 mm，尺度 %7 mm/px")
                             .arg(inside ? QStringLiteral("从外向内 · 材料外缘")
                                         : QStringLiteral("从内向外 · 孔壁内缘"))
                             .arg(bc.subpixel ? QStringLiteral("图像细化")
                                              : QStringLiteral("仅 3D"))
                             .arg(used).arg(bc.sectors)
                             .arg(fmt4(100.0 * bc.coverage)).arg(fmt4(bc.roundness))
                             .arg(fmt4(bc.mmPerPx));
    if (!bc.reliable)
        ctx.confidenceNote += QStringLiteral("；覆盖或圆度不达标，已标「参考」");
    if (!bc.debug.empty())
        ctx.confidenceNote += QStringLiteral("；") + fromStd(bc.debug);

    m_lastRadius = bc.radius;
    m_lastRoundness = bc.roundness;
    m_lastCoverage = bc.coverage;
    m_lastMmPerPx = bc.mmPerPx;
    m_lastUsed = used;
    m_lastSectors = bc.sectors;
    m_lastReliable = bc.reliable;
    m_lastSubpixel = bc.subpixel;
    m_lastMaterialInside = inside;
    m_lastCenter = bc.center;
}

bool Hole3DPage::wantsDeviationColors() const
{
    return m_devColor && m_devColor->isChecked();
}

void Hole3DPage::setDeviationColoring(bool on)
{
    if (!m_devColor)
        return;
    // 面板是唯一写者：同步勾选状态时不得反弹 deviationColoringChanged。
    const QSignalBlocker block(m_devColor);
    m_devColor->setChecked(on);
    m_devColor->update();
}

void Hole3DPage::resetResult()
{
    MeasurePage::resetResult();
    if (m_resultValue)
        updateResultDisplay();
}

void Hole3DPage::rerun()
{
    MeasurePage::rerun();
    updateResultDisplay();
}

void Hole3DPage::applyTolerance()
{
    setCustomTolerance(true, toleranceLo(), toleranceHi());
    if (hasResult())
        updateResultDisplay();
}

void Hole3DPage::onMeasure()
{
    applyTolerance();
    runMeasurement(true);
    if (hasResult()) {
        m_addButton->setEnabled(true);
        updateResultDisplay();
        setHint(QStringLiteral("测量完成：⌀%1 mm").arg(fmt4(primaryValue())), false);
        switchTab(1);
    } else {
        m_addButton->setEnabled(false);
        updateResultDisplay();
        setHint(lastHintText(), true);
    }
}

void Hole3DPage::onAddToSequence()
{
    if (!hasResult())
        return;
    const double value = primaryValue();
    m_sequence.push_back(value);
    // 共享序列库：让「重复性」工具仍能统计同一个尺寸。
    if (QMap<QString, QVector<double>>* store = seriesStore())
        (*store)[primaryKey()].append(value);
    updateSequenceUi();
    m_addButton->setEnabled(false);
    setHint(QStringLiteral("已添加到序列（第 %1 组）：%2 mm")
                .arg(static_cast<qulonglong>(m_sequence.size()))
                .arg(fmt4(value)),
            false);
}

void Hole3DPage::onCancel()
{
    resetResult();
    m_addButton->setEnabled(false);
    setHint(QStringLiteral("已取消本次测量。"), false);
    switchTab(0);
}

void Hole3DPage::refreshRoiDisplay()
{
    if (!m_roiState)
        return;
    const std::vector<MeasureTools::Vec3>& pts = roiPoints(0);
    if (pts.empty()) {
        for (int k = 0; k < 3; ++k) {
            m_start[k]->setText(QStringLiteral("0.00"));
            m_end[k]->setText(QStringLiteral("0.00"));
        }
        m_roiState->setText(
            QStringLiteral("未选择 — 在 2D 视图上按住左键拖框（只需 ROI A）"));
        return;
    }
    double lo[3] = { std::numeric_limits<double>::max(),
                     std::numeric_limits<double>::max(),
                     std::numeric_limits<double>::max() };
    double hi[3] = { std::numeric_limits<double>::lowest(),
                     std::numeric_limits<double>::lowest(),
                     std::numeric_limits<double>::lowest() };
    for (const MeasureTools::Vec3& p : pts) {
        for (int k = 0; k < 3; ++k) {
            lo[k] = std::min(lo[k], p[k]);
            hi[k] = std::max(hi[k], p[k]);
        }
    }
    for (int k = 0; k < 3; ++k) {
        m_start[k]->setText(fmt4(lo[k]));
        m_end[k]->setText(fmt4(hi[k]));
    }
    m_roiState->setText(roiText(0));
}

void Hole3DPage::updateResultDisplay()
{
    if (!m_resultValue || !m_resultTag)
        return;
    if (!hasResult()) {
        m_resultValue->setText(QStringLiteral("--"));
        m_resultValue->setStyleSheet(
            QStringLiteral("color:%1; background:transparent; border:none;")
                .arg(kTextMuted));
        m_resultDetail->clear();
        m_resultTag->setText(QStringLiteral("等待测量"));
        m_resultTag->setStyleSheet(
            QStringLiteral("color:%1; background:#e2e8f0; border:none;"
                           " border-radius:14px; padding:6px 22px;")
                .arg(kTextMuted));
        return;
    }

    const double value = primaryValue();
    const bool ok = value >= toleranceLo() && value <= toleranceHi();
    m_resultValue->setText(fmt4(value));
    m_resultValue->setStyleSheet(
        QStringLiteral("color:%1; background:transparent; border:none;")
            .arg(ok ? kBlue : kRed));
    updateGeometryDetail();
    m_resultTag->setText(ok ? QStringLiteral("合格 (OK)") : QStringLiteral("超差 (NG)"));
    m_resultTag->setStyleSheet(
        QStringLiteral("color:#ffffff; background:%1; border:none;"
                       " border-radius:14px; padding:6px 22px;")
            .arg(ok ? kGreen : kRed));
}

void Hole3DPage::updateGeometryDetail()
{
    if (!m_resultDetail)
        return;
    if (!hasResult()) {
        m_resultDetail->clear();
        return;
    }
    const int mode = m_geometry ? m_geometry->currentIndex() : 2;
    QStringList parts;
    if (mode == 0 || mode == 2) {
        parts << QStringLiteral("%1半径 %2 mm")
                     .arg(m_lastMaterialInside ? QStringLiteral("外缘") : QStringLiteral("孔"))
                     .arg(fmt4(m_lastRadius));
    }
    if (mode == 1 || mode == 2) {
        parts << QStringLiteral("圆心 (%1, %2, %3) mm")
                     .arg(fmt4(m_lastCenter[0]), fmt4(m_lastCenter[1]),
                          fmt4(m_lastCenter[2]));
    }
    parts << QStringLiteral("圆度 %1 mm · 扇区覆盖 %2/%3%4")
                 .arg(fmt4(m_lastRoundness))
                 .arg(m_lastUsed)
                 .arg(m_lastSectors)
                 .arg(m_lastReliable ? QString() : QStringLiteral("（参考）"));
    m_resultDetail->setText(parts.join(QStringLiteral("\n")));
}

void Hole3DPage::updateSequenceUi()
{
    if (!m_seqCount || !m_historyLayout)
        return;
    m_seqCount->setText(QStringLiteral("%1 组数据")
                            .arg(static_cast<qulonglong>(m_sequence.size())));

    // 先清空旧行（末尾的 stretch 也一起删掉，稍后补回）。
    while (QLayoutItem* item = m_historyLayout->takeAt(0)) {
        delete item->widget();   // 行只属于这个布局，立即删掉（不留在画面上）
        delete item;
    }

    if (m_sequence.empty()) {
        m_statMax->setText(QStringLiteral("--"));
        m_statMin->setText(QStringLiteral("--"));
        m_statAvg->setText(QStringLiteral("--"));
        m_statRange->setText(QStringLiteral("--"));
        auto* empty = new QLabel(QStringLiteral("暂无历史数据"), m_historyHost);
        empty->setObjectName(QStringLiteral("hole3dHistoryEmpty"));
        empty->setAlignment(Qt::AlignCenter);
        m_historyLayout->addWidget(empty);
        m_historyLayout->addStretch();
        return;
    }

    const auto mm = std::minmax_element(m_sequence.begin(), m_sequence.end());
    double sum = 0.0;
    for (double v : m_sequence)
        sum += v;
    m_statMax->setText(fmt4(*mm.second));
    m_statMin->setText(fmt4(*mm.first));
    m_statAvg->setText(fmt4(sum / static_cast<double>(m_sequence.size())));
    m_statRange->setText(fmt4(*mm.second - *mm.first));

    // 2.html：最新的在最上面。
    for (int i = static_cast<int>(m_sequence.size()) - 1; i >= 0; --i) {
        auto* row = new QWidget(m_historyHost);
        auto* h = new QHBoxLayout(row);
        h->setContentsMargins(0, 6, 0, 6);
        h->setSpacing(8);
        auto* name = new QLabel(QStringLiteral("第 %1 次测量").arg(i + 1), row);
        name->setObjectName(QStringLiteral("hole3dHistoryName"));
        auto* value = new QLabel(fmt4(m_sequence[static_cast<std::size_t>(i)])
                                     + QStringLiteral(" mm"), row);
        value->setObjectName(QStringLiteral("hole3dHistoryValue"));
        h->addWidget(name);
        h->addStretch();
        h->addWidget(value);
        m_historyLayout->addWidget(row);
    }
    m_historyLayout->addStretch();
}

void Hole3DPage::setHint(const QString& text, bool error)
{
    if (!m_hint)
        return;
    m_hint->setText(text);
    m_hint->setStyleSheet(
        QStringLiteral("color:%1; font-size:12px; border:none;")
            .arg(error ? kRed : kGreen));
}
