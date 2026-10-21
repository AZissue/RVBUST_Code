#include "ui/RobotProgramPanel.h"

#include "app/RobotProgramController.h"
#include "logic/JogPolicy.h"

#include <QAbstractButton>
#include <QButtonGroup>
#include <QComboBox>
#include <QDialog>
#include <QDoubleSpinBox>
#include <QFontMetrics>
#include <QFrame>
#include <QGraphicsDropShadowEffect>
#include <QHBoxLayout>
#include <QLabel>
#include <QLayoutItem>
#include <QLineEdit>
#include <QMouseEvent>
#include <QPalette>
#include <QPushButton>
#include <QResizeEvent>
#include <QScrollArea>
#include <QSignalBlocker>
#include <QSlider>
#include <QSpinBox>
#include <QSplitter>
#include <QStackedWidget>
#include <QTimer>
#include <QToolButton>
#include <QVBoxLayout>

#include <algorithm>
#include <cmath>
#include <functional>
#include <variant>

namespace {

// ── 设计变量：逐项对应 MyUIdesign/1.html 的 :root ─────────────────────
constexpr const char* kPrimary = "#1890ff";
constexpr const char* kSuccess = "#52c41a";
constexpr const char* kDanger = "#ff4d4f";
constexpr const char* kWarning = "#faad14";
constexpr const char* kBg = "#eef1f6";
constexpr const char* kBorder = "#d9d9d9";
constexpr const char* kTextMain = "#333333";
constexpr const char* kTextSub = "#888888";

QLabel* textLabel(const QString& text, int px, const char* color,
                  bool bold = false)
{
    auto* label = new QLabel(text);
    label->setStyleSheet(
        QStringLiteral("font-size:%1px;font-weight:%2;color:%3;"
                       "background:transparent;")
            .arg(px)
            .arg(bold ? 600 : 400)
            .arg(color));
    return label;
}

void applyCardShadow(QWidget* widget)
{
    auto* shadow = new QGraphicsDropShadowEffect(widget);
    shadow->setBlurRadius(12);
    shadow->setOffset(0, 2);
    shadow->setColor(QColor(0, 0, 0, 28));
    widget->setGraphicsEffect(shadow);
}

QString cardStyle()
{
    return QStringLiteral(
        "QFrame#rpCard { background:#ffffff; border-radius:8px; }");
}

QString sectionTitleStyle()
{
    return QStringLiteral(
        "font-size:13px;font-weight:bold;color:%1;"
        "border-left:4px solid %2;padding-left:8px;background:transparent;")
        .arg(kTextMain, kPrimary);
}

QString outlineButtonStyle(bool danger)
{
    if (danger) {
        return QStringLiteral(
            "QPushButton { background:#ffffff; border:1px solid #ffccc7;"
            " border-radius:4px; color:%1; font-size:13px; font-weight:bold;"
            " padding:8px 10px; }"
            "QPushButton:hover:enabled { border-color:%1; color:%1; }"
            "QPushButton:pressed:enabled { background:#fff1f0; }"
            "QPushButton:disabled { background:#fafafa; border-color:#e8e8e8;"
            " color:#bfbfbf; }")
            .arg(kDanger);
    }
    return QStringLiteral(
        "QPushButton { background:#ffffff; border:1px solid %1;"
        " border-radius:4px; color:%2; font-size:13px; font-weight:bold;"
        " padding:8px 10px; }"
        "QPushButton:hover:enabled { border-color:%3; color:%3; }"
        "QPushButton:pressed:enabled { background:#e6f7ff; }"
        "QPushButton:disabled { background:#fafafa; border-color:#e8e8e8;"
        " color:#bfbfbf; }")
        .arg(kBorder, kTextMain, kPrimary);
}

QString axisButtonStyle()
{
    return QStringLiteral(
        "QPushButton { background:#e6f7ff; border:1px solid %1;"
        " border-radius:6px; color:%1; font-size:24px; font-weight:bold; }"
        "QPushButton:hover:enabled { background:%1; color:#ffffff; }"
        "QPushButton:pressed:enabled { background:#096dd9; }"
        "QPushButton:disabled { background:#f5f5f5; border-color:#d9d9d9;"
        " color:#cccccc; }")
        .arg(kPrimary);
}

QString jointButtonStyle()
{
    return QStringLiteral(
        "QPushButton { background:#e6f7ff; border:1px solid #91d5ff;"
        " border-radius:4px; color:%1; font-size:18px; font-weight:bold; }"
        "QPushButton:hover:enabled { background:%1; border-color:%1;"
        " color:#ffffff; }"
        "QPushButton:disabled { background:#f5f5f5; border-color:#d9d9d9;"
        " color:#cccccc; }")
        .arg(kPrimary);
}

QString cartEditStyle()
{
    return QStringLiteral(
        "QLineEdit { border:1px solid %1; border-radius:6px; background:#fff;"
        " color:%2; font-size:16px; font-family:Consolas,monospace;"
        " padding:0 8px; }"
        "QLineEdit:focus { border-color:%3; }"
        "QLineEdit[readOnly=\"true\"] { background:#ffffff; color:%2; }")
        .arg(kBorder, kTextMain, kPrimary);
}

QString jointEditStyle()
{
    return QStringLiteral(
        "QLineEdit { border:1px solid #cccccc; border-radius:4px;"
        " background:#fff; color:%1; font-size:13px;"
        " font-family:Consolas,monospace; padding:4px; }"
        "QLineEdit:focus { border-color:%2; }"
        "QLineEdit[readOnly=\"true\"] { background:#ffffff; color:%1; }")
        .arg(kTextMain, kPrimary);
}

QString smallInputStyle()
{
    return QStringLiteral(
        "QLineEdit, QSpinBox, QDoubleSpinBox { border:1px solid #cccccc;"
        " border-radius:4px; background:#ffffff; color:%1; font-size:13px;"
        " padding:5px 7px; }"
        "QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {"
        " border-color:%2; }"
        "QLineEdit:disabled, QSpinBox:disabled { background:#f5f5f5;"
        " color:#999999; }")
        .arg(kTextMain, kPrimary);
}

QString comboStyle()
{
    return QStringLiteral(
        "QComboBox { border:1px solid #cccccc; border-radius:4px;"
        " background:#ffffff; color:%1; font-size:13px; padding:3px 8px; }"
        "QComboBox:disabled { background:#f5f5f5; color:#999999; }"
        "QComboBox QAbstractItemView { background:#ffffff; color:%1;"
        " selection-background-color:#e6f7ff; selection-color:%2; }")
        .arg(kTextMain, kPrimary);
}

QString sliderStyle()
{
    return QStringLiteral(
        "QSlider::groove:horizontal { height:4px; background:#e0e0e0;"
        " border-radius:2px; }"
        "QSlider::sub-page:horizontal { height:4px; background:%1;"
        " border-radius:2px; }"
        "QSlider::handle:horizontal { width:14px; height:14px; margin:-5px 0;"
        " background:#ffffff; border:2px solid %1; border-radius:8px; }"
        "QSlider::handle:horizontal:disabled { border-color:#d9d9d9; }")
        .arg(kPrimary);
}

QString segmentedStyle(bool active)
{
    if (active) {
        return QStringLiteral(
            "QPushButton { background:#ffffff; color:%1; border:none;"
            " border-radius:4px; padding:8px; font-size:13px;"
            " font-weight:bold; }")
            .arg(kPrimary);
    }
    return QStringLiteral(
        "QPushButton { background:transparent; color:#666666; border:none;"
        " border-radius:4px; padding:8px; font-size:13px; font-weight:bold; }"
        "QPushButton:hover:enabled { color:%1; }"
        "QPushButton:disabled { color:#aaaaaa; }")
        .arg(kPrimary);
}

QString enableButtonStyle()
{
    return QStringLiteral(
        "QPushButton { background:#ffffff; color:%1; border:1px solid %1;"
        " border-radius:4px; padding:8px 16px; font-size:14px;"
        " font-weight:bold; }"
        "QPushButton:hover:enabled { background:#f6ffed; }"
        "QPushButton:checked { background:%1; color:#ffffff; }"
        "QPushButton:disabled { background:#ffffff; border-color:#d9d9d9;"
        " color:#999999; }")
        .arg(kSuccess);
}

QString stopButtonStyle()
{
    return QStringLiteral(
        "QPushButton { background:%1; color:#ffffff; border:none;"
        " border-radius:4px; padding:8px 24px; font-size:15px;"
        " font-weight:bold; }"
        "QPushButton:hover:enabled { background:#ff7875; }"
        "QPushButton:disabled { background:#ffccc7; }")
        .arg(kDanger);
}

QString runButtonStyle(const char* color, const char* hover)
{
    return QStringLiteral(
        "QPushButton { background:%1; color:#ffffff; border:none;"
        " border-radius:4px; padding:12px; font-size:15px;"
        " font-weight:bold; }"
        "QPushButton:hover:enabled { background:%2; }"
        "QPushButton:disabled { background:#f5f5f5; color:#999999; }")
        .arg(color, hover);
}

QString nodeRowStyle(bool selected, bool running)
{
    QString border = QStringLiteral("#e8e8e8");
    QString background = QStringLiteral("#ffffff");
    if (selected) {
        border = kPrimary;
        background = QStringLiteral("#e6f7ff");
    }
    if (running) {
        border = kSuccess;
        background = QStringLiteral("#f6ffed");
    }
    return QStringLiteral(
        "QFrame#rpNodeRow { background:%1; border:1px solid %2;"
        " border-radius:4px; }")
        .arg(background, border);
}

QString tagStyle(RobotProgram::NodeKind kind)
{
    const char* color = kPrimary;
    if (kind == RobotProgram::NodeKind::Photo)
        color = "#722ed1";
    else if (kind == RobotProgram::NodeKind::Wait)
        color = kWarning;
    return QStringLiteral(
        "QLabel { background:%1; color:#ffffff; border-radius:3px;"
        " padding:2px 6px; font-size:12px; }")
        .arg(color);
}

QString number2(double v)
{
    return QString::number(v, 'f', 2);
}

QString number1(double v)
{
    return QString::number(v, 'f', 1);
}

// 点击可选中；用 std::function 而不是信号，省一个 Q_OBJECT 派生类。
class NodeRowFrame : public QFrame {
public:
    explicit NodeRowFrame(std::function<void()> onClick,
                          QWidget* parent = nullptr)
        : QFrame(parent)
        , m_onClick(std::move(onClick))
    {
        setCursor(Qt::PointingHandCursor);
    }

protected:
    void mousePressEvent(QMouseEvent* event) override
    {
        if (event->button() == Qt::LeftButton && m_onClick)
            m_onClick();
        QFrame::mousePressEvent(event);
    }

private:
    std::function<void()> m_onClick;
};

// 详情列在左卡变窄时省略号收尾，而不是把整行撑出横向滚动条。
// 底部四个按钮在窄窗口里自动换行（宽时仍是一行，与 1.html 一致）。
// 用流式布局而不是固定 2×2：默认窗口 820 宽时左侧只有约 280 px，
// 一行放不下四个按钮，固定行会把按钮压到看不清字。
class FlowLayout : public QLayout {
public:
    explicit FlowLayout(QWidget* parent = nullptr, int hSpacing = 8,
                        int vSpacing = 8)
        : QLayout(parent), m_hSpace(hSpacing), m_vSpace(vSpacing) {}
    ~FlowLayout() override
    {
        while (QLayoutItem* item = takeAt(0))
            delete item;
    }

    void addItem(QLayoutItem* item) override { m_items.append(item); }
    int count() const override { return m_items.size(); }
    QLayoutItem* itemAt(int index) const override
    {
        return m_items.value(index);
    }
    QLayoutItem* takeAt(int index) override
    {
        return index >= 0 && index < m_items.size() ? m_items.takeAt(index)
                                                    : nullptr;
    }
    Qt::Orientations expandingDirections() const override { return {}; }
    bool hasHeightForWidth() const override { return true; }
    int heightForWidth(int width) const override
    {
        return doLayout(QRect(0, 0, width, 0), true);
    }
    void setGeometry(const QRect& rect) override
    {
        QLayout::setGeometry(rect);
        doLayout(rect, false);
    }
    QSize sizeHint() const override
    {
        const QMargins m = contentsMargins();
        int width = 0;
        int height = 0;
        for (QLayoutItem* item : m_items) {
            const QSize hint = item->sizeHint();
            width += (width > 0 ? m_hSpace : 0) + hint.width();
            height = std::max(height, hint.height());
        }
        return QSize(width + m.left() + m.right(),
                     height + m.top() + m.bottom());
    }
    QSize minimumSize() const override
    {
        QSize size;
        for (QLayoutItem* item : m_items)
            size = size.expandedTo(item->minimumSize());
        const QMargins m = contentsMargins();
        return size
            + QSize(m.left() + m.right(), m.top() + m.bottom());
    }

private:
    int doLayout(const QRect& rect, bool testOnly) const
    {
        const QMargins m = contentsMargins();
        const QRect area = rect.adjusted(m.left(), m.top(), -m.right(),
                                         -m.bottom());
        int x = area.x();
        int y = area.y();
        int lineHeight = 0;
        for (QLayoutItem* item : m_items) {
            const QSize hint = item->sizeHint();
            if (x + hint.width() > area.right() + 1 && lineHeight > 0) {
                x = area.x();
                y += lineHeight + m_vSpace;
                lineHeight = 0;
            }
            if (!testOnly)
                item->setGeometry(QRect(QPoint(x, y), hint));
            x += hint.width() + m_hSpace;
            lineHeight = std::max(lineHeight, hint.height());
        }
        return y + lineHeight - rect.y() + m.bottom();
    }

    QList<QLayoutItem*> m_items;
    int m_hSpace = 8;
    int m_vSpace = 8;
};

// 按住不放时连续点动：先立即走一步，按住 400 ms 后每 160 ms 再走一步。
// 400 ms 的延迟保证普通单击仍然只走一步。
class RepeatButton : public QPushButton {
public:
    explicit RepeatButton(QWidget* parent = nullptr) : QPushButton(parent)
    {
        m_delay.setSingleShot(true);
        m_delay.setInterval(400);
        m_repeat.setInterval(160);
        connect(&m_delay, &QTimer::timeout, this, [this]() {
            if (isEnabled())
                m_repeat.start();
        });
        connect(&m_repeat, &QTimer::timeout, this, [this]() {
            if (isEnabled())
                emit clicked();
        });
    }

protected:
    void mousePressEvent(QMouseEvent* event) override
    {
        QPushButton::mousePressEvent(event);
        if (event->button() == Qt::LeftButton && isEnabled())
            m_delay.start();
    }
    void mouseReleaseEvent(QMouseEvent* event) override
    {
        m_delay.stop();
        m_repeat.stop();
        QPushButton::mouseReleaseEvent(event);
    }
    void leaveEvent(QEvent* event) override
    {
        m_delay.stop();
        m_repeat.stop();
        QPushButton::leaveEvent(event);
    }

private:
    QTimer m_delay;
    QTimer m_repeat;
};

class ElideLabel : public QLabel {
public:
    explicit ElideLabel(QWidget* parent = nullptr) : QLabel(parent)
    {
        setAlignment(Qt::AlignRight | Qt::AlignVCenter);
        setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
        setMinimumWidth(0);
    }

    void setFullText(const QString& text)
    {
        m_full = text;
        setToolTip(text);
        updateElided();
    }

protected:
    void resizeEvent(QResizeEvent* event) override
    {
        QLabel::resizeEvent(event);
        updateElided();
    }

private:
    void updateElided()
    {
        setText(fontMetrics().elidedText(m_full, Qt::ElideRight,
                                         std::max(0, width())));
    }

    QString m_full;
};

} // namespace

RobotProgramPanel::RobotProgramPanel(QWidget* parent) : QWidget(parent)
{
    buildUi();
    refreshNodes();
    refreshPadValues();
    refreshActions();
}

void RobotProgramPanel::buildUi()
{
    setObjectName(QStringLiteral("robot_program_page"));
    setAutoFillBackground(true);
    QPalette pal = palette();
    pal.setColor(QPalette::Window, QColor(kBg));
    setPalette(pal);
    // 工具窗口默认只有 820×620，左侧列表占掉约 150 px 后，页面实际只有
    // 约 610 px。这里按「最小可用」定宽（560），左右卡片用 splitter 分配，
    // 宽窗口自动把多余空间给节点列表，窄窗口先压缩右侧控制卡。
    setMinimumWidth(560);

    auto* root = new QVBoxLayout(this);
    root->setContentsMargins(15, 15, 15, 15);
    root->setSpacing(15);

    root->addWidget(buildTopBar());

    auto* splitter = new QSplitter(Qt::Horizontal);
    splitter->setChildrenCollapsible(false);
    splitter->setHandleWidth(15);
    splitter->setStyleSheet(QStringLiteral("QSplitter::handle { background:transparent; }"));
    splitter->addWidget(buildLeftCard());
    splitter->addWidget(buildRightCard());
    splitter->setStretchFactor(0, 1);
    splitter->setStretchFactor(1, 0);
    splitter->setSizes({ 700, 420 });
    root->addWidget(splitter, 1);

    m_toast = new QLabel(this);
    m_toast->setAlignment(Qt::AlignCenter);
    m_toast->setAttribute(Qt::WA_TransparentForMouseEvents);
    m_toast->setStyleSheet(
        QStringLiteral("QLabel { background:rgba(0,0,0,190); color:#ffffff;"
                       " padding:10px 24px; border-radius:4px;"
                       " font-size:14px; }"));
    m_toast->hide();

    m_toastTimer = new QTimer(this);
    m_toastTimer->setSingleShot(true);
    connect(m_toastTimer, &QTimer::timeout, m_toast, &QLabel::hide);

    onModeChanged(0);
}

QWidget* RobotProgramPanel::buildTopBar()
{
    auto* bar = new QFrame;
    bar->setObjectName(QStringLiteral("rpTopBar"));
    bar->setStyleSheet(QStringLiteral(
        "QFrame#rpTopBar { background:#ffffff; border-radius:8px; }"));

    auto* row = new QHBoxLayout(bar);
    row->setContentsMargins(20, 10, 20, 10);
    row->setSpacing(10);

    m_statusDot = new QLabel;
    m_statusDot->setFixedSize(12, 12);
    m_statusDot->setStyleSheet(
        QStringLiteral("background:%1;border-radius:6px;").arg(kBorder));
    row->addWidget(m_statusDot);

    m_connLabel = textLabel(QStringLiteral("通信未连接"), 14, "#666666", true);
    row->addWidget(m_connLabel);
    row->addSpacing(10);

    auto* speedTitle = textLabel(QStringLiteral("运行速度:"), 13, "#666666");
    row->addWidget(speedTitle);
    m_speedSlider = new QSlider(Qt::Horizontal);
    m_speedSlider->setObjectName(QStringLiteral("robot_program_speed"));
    m_speedSlider->setRange(static_cast<int>(JogPolicy::MIN_SPEED),
                            static_cast<int>(JogPolicy::MAX_SPEED));
    m_speedSlider->setValue(50);
    // 窗口窄时滑杆收缩到 60 px，给右侧使能/停止留位置。
    m_speedSlider->setMinimumWidth(60);
    m_speedSlider->setMaximumWidth(110);
    m_speedSlider->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    m_speedSlider->setStyleSheet(sliderStyle());
    m_speedSlider->setToolTip(
        QStringLiteral("点动速度，也是新建移动节点的默认速度。"));
    row->addWidget(m_speedSlider);
    m_speedLabel = textLabel(QStringLiteral("50%"), 13, "#666666");
    m_speedLabel->setMinimumWidth(38);
    row->addWidget(m_speedLabel);

    row->addStretch(1);

    m_enableButton = new QPushButton(QStringLiteral("⚡ 开启使能"));
    m_enableButton->setObjectName(QStringLiteral("robot_program_enable"));
    m_enableButton->setCheckable(true);
    m_enableButton->setCursor(Qt::PointingHandCursor);
    m_enableButton->setMinimumHeight(34);
    m_enableButton->setStyleSheet(enableButtonStyle());
    m_enableButton->setToolTip(
        QStringLiteral("软件运动许可；UR 真机还要求控制器处于 RUNNING。"));
    row->addWidget(m_enableButton);
    row->addSpacing(5);

    m_stopButton = new QPushButton(QStringLiteral("停止 (STOP)"));
    m_stopButton->setObjectName(QStringLiteral("robot_program_stop"));
    m_stopButton->setCursor(Qt::PointingHandCursor);
    m_stopButton->setMinimumHeight(34);
    m_stopButton->setMinimumWidth(100);
    m_stopButton->setStyleSheet(stopButtonStyle());
    m_stopButton->setToolTip(
        QStringLiteral("软件停止：终止当前程序并停下运动。"
                       "安全级停止请使用示教器。"));
    row->addWidget(m_stopButton);

    connect(m_speedSlider, &QSlider::valueChanged, this, [this](int v) {
        m_speedLabel->setText(QStringLiteral("%1%").arg(v));
        if (m_controller)
            m_controller->setJogSpeed(v);
    });
    connect(m_enableButton, &QPushButton::toggled, this,
            &RobotProgramPanel::onEnableToggled);
    connect(m_stopButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onStopClicked);

    applyCardShadow(bar);
    return bar;
}

QWidget* RobotProgramPanel::buildLeftCard()
{
    auto* card = new QFrame;
    card->setObjectName(QStringLiteral("rpCard"));
    card->setStyleSheet(cardStyle());
    card->setMinimumWidth(240);

    auto* column = new QVBoxLayout(card);
    column->setContentsMargins(0, 0, 0, 0);
    column->setSpacing(0);

    auto* header = new QFrame;
    header->setObjectName(QStringLiteral("rpListHeader"));
    header->setStyleSheet(QStringLiteral(
        "QFrame#rpListHeader { background:#fafafa; border:none;"
        " border-top-left-radius:8px; border-top-right-radius:8px;"
        " border-bottom:1px solid #eeeeee; }"));
    auto* headerRow = new QHBoxLayout(header);
    headerRow->setContentsMargins(15, 14, 15, 14);
    headerRow->addWidget(
        textLabel(QStringLiteral("流程节点列表"), 14, kTextMain, true));
    headerRow->addStretch(1);
    m_countLabel = textLabel(QStringLiteral("共 0 个节点"), 12, "#999999");
    headerRow->addWidget(m_countLabel);
    column->addWidget(header);

    m_listScroll = new QScrollArea;
    m_listScroll->setObjectName(QStringLiteral("robot_program_nodes"));
    m_listScroll->setFrameShape(QFrame::NoFrame);
    m_listScroll->setWidgetResizable(true);
    m_listScroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_listScroll->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    m_listScroll->setStyleSheet(
        QStringLiteral("QScrollArea { background:transparent; }"));
    m_listScroll->viewport()->setStyleSheet(
        QStringLiteral("background:transparent;"));

    m_listContainer = new QWidget;
    m_listContainer->setStyleSheet(QStringLiteral("background:transparent;"));
    m_listLayout = new QVBoxLayout(m_listContainer);
    m_listLayout->setContentsMargins(10, 10, 10, 10);
    m_listLayout->setSpacing(8);
    m_listLayout->setAlignment(Qt::AlignTop);
    m_listScroll->setWidget(m_listContainer);
    column->addWidget(m_listScroll, 1);

    auto* bottom = new QFrame;
    bottom->setObjectName(QStringLiteral("rpListFooter"));
    bottom->setStyleSheet(QStringLiteral(
        "QFrame#rpListFooter { background:#fafafa; border:none;"
        " border-bottom-left-radius:8px; border-bottom-right-radius:8px;"
        " border-top:1px solid #eeeeee; }"));
    // 四个按钮用流式布局：宽时一行，窄时自动两行两列，不把文字挤掉。
    auto* bottomRow = new FlowLayout(bottom, 8, 8);
    bottomRow->setContentsMargins(12, 10, 12, 10);

    m_addMoveButton = new QPushButton(QStringLiteral("＋ 添加移动"));
    m_addMoveButton->setObjectName(QStringLiteral("robot_program_add_move"));
    m_addPhotoButton = new QPushButton(QStringLiteral("📷 拍照采集"));
    m_addPhotoButton->setObjectName(QStringLiteral("robot_program_add_photo"));
    m_addWaitButton = new QPushButton(QStringLiteral("⏱ 等待时间"));
    m_addWaitButton->setObjectName(QStringLiteral("robot_program_add_wait"));
    m_deleteButton = new QPushButton(QStringLiteral("🗑 删除选中"));
    m_deleteButton->setObjectName(QStringLiteral("robot_program_delete"));

    for (auto* button : { m_addMoveButton, m_addPhotoButton,
                          m_addWaitButton }) {
        button->setCursor(Qt::PointingHandCursor);
        button->setMinimumHeight(36);
        button->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
        button->setStyleSheet(outlineButtonStyle(false));
        bottomRow->addWidget(button);
    }
    m_deleteButton->setCursor(Qt::PointingHandCursor);
    m_deleteButton->setMinimumHeight(36);
    m_deleteButton->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    m_deleteButton->setStyleSheet(outlineButtonStyle(true));
    bottomRow->addWidget(m_deleteButton);
    column->addWidget(bottom);

    m_addPhotoButton->setToolTip(QStringLiteral(
        "拍照节点会读取已连接机器人的实时位姿；请先连接机器人。"));

    connect(m_addMoveButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onAddMove);
    connect(m_addPhotoButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onAddPhoto);
    connect(m_addWaitButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onAddWait);
    connect(m_deleteButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onDeleteNode);

    applyCardShadow(card);
    return card;
}

QWidget* RobotProgramPanel::buildCommSection()
{
    auto* section = new QFrame;
    section->setObjectName(QStringLiteral("rpComm"));
    section->setStyleSheet(QStringLiteral(
        "QFrame#rpComm { background:#fafafa; border:1px solid %1;"
        " border-radius:6px; }")
        .arg(kBorder));

    auto* column = new QVBoxLayout(section);
    column->setContentsMargins(10, 8, 10, 10);
    column->setSpacing(8);

    m_commHeader = new QToolButton;
    m_commHeader->setText(QStringLiteral("⚙️ 机器人通信配置"));
    m_commHeader->setCheckable(true);
    m_commHeader->setChecked(true);
    m_commHeader->setAutoRaise(true);
    m_commHeader->setToolButtonStyle(Qt::ToolButtonTextBesideIcon);
    m_commHeader->setArrowType(Qt::DownArrow);
    m_commHeader->setCursor(Qt::PointingHandCursor);
    m_commHeader->setStyleSheet(QStringLiteral(
        "QToolButton { color:%1; font-size:13px; font-weight:bold;"
        " border:none; background:transparent; padding:0; }")
        .arg(kPrimary));
    column->addWidget(m_commHeader);

    m_commBody = new QWidget;
    auto* body = new QVBoxLayout(m_commBody);
    body->setContentsMargins(0, 6, 0, 0);
    body->setSpacing(8);

    auto* backendRow = new QHBoxLayout;
    backendRow->setSpacing(8);
    backendRow->addWidget(textLabel(QStringLiteral("后端"), 13, kTextSub));
    m_backendCombo = new QComboBox;
    m_backendCombo->setObjectName(QStringLiteral("robot_program_backend"));
    m_backendCombo->addItem(QStringLiteral("仿真"));
    m_backendCombo->addItem(QStringLiteral("UR 真机"));
    m_backendCombo->setStyleSheet(comboStyle());
    m_backendCombo->setMinimumHeight(30);
    backendRow->addWidget(m_backendCombo, 1);
    body->addLayout(backendRow);

    auto* addressRow = new QHBoxLayout;
    addressRow->setSpacing(6);
    addressRow->addWidget(textLabel(QStringLiteral("IP:"), 13, kTextSub));
    m_hostEdit = new QLineEdit(QStringLiteral("192.168.0.38"));
    m_hostEdit->setObjectName(QStringLiteral("robot_program_host"));
    m_hostEdit->setStyleSheet(smallInputStyle());
    m_hostEdit->setMinimumHeight(30);
    addressRow->addWidget(m_hostEdit, 1);
    addressRow->addWidget(textLabel(QStringLiteral("端口:"), 13, kTextSub));
    m_portSpin = new QSpinBox;
    m_portSpin->setRange(1, 65535);
    m_portSpin->setValue(30003);
    m_portSpin->setFixedWidth(76);
    m_portSpin->setMinimumHeight(30);
    m_portSpin->setStyleSheet(smallInputStyle());
    m_portSpin->setToolTip(QStringLiteral(
        "UR 实时反馈端口。脚本 30001 与 Dashboard 29999 固定，自动使用。"));
    addressRow->addWidget(m_portSpin);
    body->addLayout(addressRow);

    m_connectButton = new QPushButton(QStringLiteral("🔌 连接"));
    m_connectButton->setObjectName(QStringLiteral("robot_program_connect"));
    m_connectButton->setCursor(Qt::PointingHandCursor);
    m_connectButton->setMinimumHeight(32);
    m_connectButton->setStyleSheet(QStringLiteral(
        "QPushButton { background:%1; color:#ffffff; border:none;"
        " border-radius:4px; font-size:14px; font-weight:bold;"
        " padding:6px; }"
        "QPushButton:hover:enabled { background:#40a9ff; }"
        "QPushButton:disabled { background:#f5f5f5; color:#999999; }")
        .arg(kPrimary));
    body->addWidget(m_connectButton);

    column->addWidget(m_commBody);

    connect(m_commHeader, &QToolButton::toggled, this, [this](bool open) {
        m_commBody->setVisible(open);
        m_commHeader->setArrowType(open ? Qt::DownArrow : Qt::RightArrow);
    });
    connect(m_backendCombo,
            QOverload<int>::of(&QComboBox::currentIndexChanged), this,
            &RobotProgramPanel::onBackendKindChanged);
    connect(m_connectButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onConnectClicked);

    return section;
}

QWidget* RobotProgramPanel::buildRightCard()
{
    auto* card = new QFrame;
    card->setObjectName(QStringLiteral("rpCard"));
    card->setStyleSheet(cardStyle());
    // 设计稿宽 420；窄窗口允许压到 280，宽窗口最多 460。
    card->setMinimumWidth(280);
    card->setMaximumWidth(460);

    auto* column = new QVBoxLayout(card);
    column->setContentsMargins(0, 0, 0, 0);
    column->setSpacing(0);

    auto* scroll = new QScrollArea;
    scroll->setFrameShape(QFrame::NoFrame);
    scroll->setWidgetResizable(true);
    scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    scroll->setStyleSheet(QStringLiteral("QScrollArea { background:transparent; }"));
    scroll->viewport()->setStyleSheet(QStringLiteral("background:transparent;"));

    auto* body = new QWidget;
    body->setStyleSheet(QStringLiteral("background:transparent;"));
    auto* bodyColumn = new QVBoxLayout(body);
    bodyColumn->setContentsMargins(15, 15, 15, 15);
    bodyColumn->setSpacing(15);

    m_commSection = buildCommSection();
    bodyColumn->addWidget(m_commSection);

    // 编辑提示条
    m_editBanner = new QFrame;
    m_editBanner->setObjectName(QStringLiteral("rpEditBanner"));
    m_editBanner->setStyleSheet(QStringLiteral(
        "QFrame#rpEditBanner { background:#e6f7ff; border:1px solid #91d5ff;"
        " border-radius:4px; }"));
    auto* bannerRow = new QHBoxLayout(m_editBanner);
    bannerRow->setContentsMargins(15, 10, 10, 10);
    bannerRow->setSpacing(8);
    m_editBannerText =
        textLabel(QStringLiteral("正在编辑节点"), 14, kPrimary, true);
    bannerRow->addWidget(m_editBannerText);
    bannerRow->addStretch(1);
    m_captureButton = new QPushButton(QStringLiteral("用当前位姿"));
    m_captureButton->setCursor(Qt::PointingHandCursor);
    m_captureButton->setStyleSheet(QStringLiteral(
        "QPushButton { background:transparent; border:1px solid %1;"
        " color:%1; padding:2px 8px; border-radius:3px; font-size:12px; }"
        "QPushButton:hover:enabled { background:#bae7ff; }"
        "QPushButton:disabled { border-color:#d9d9d9; color:#bfbfbf; }")
        .arg(kPrimary));
    bannerRow->addWidget(m_captureButton);
    m_cancelEditButton = new QPushButton(QStringLiteral("取消编辑"));
    m_cancelEditButton->setCursor(Qt::PointingHandCursor);
    m_cancelEditButton->setStyleSheet(m_captureButton->styleSheet());
    bannerRow->addWidget(m_cancelEditButton);
    m_editBanner->hide();
    bodyColumn->addWidget(m_editBanner);

    // 模式切换
    m_modeSwitcher = new QFrame;
    m_modeSwitcher->setObjectName(QStringLiteral("rpSegmented"));
    m_modeSwitcher->setStyleSheet(QStringLiteral(
        "QFrame#rpSegmented { background:#f0f0f0; border-radius:4px; }"));
    auto* segRow = new QHBoxLayout(m_modeSwitcher);
    segRow->setContentsMargins(2, 2, 2, 2);
    segRow->setSpacing(0);
    m_cartTab = new QPushButton(QStringLiteral("笛卡尔控制"));
    m_jointTab = new QPushButton(QStringLiteral("关节控制"));
    m_modeGroup = new QButtonGroup(this);
    m_modeGroup->setExclusive(true);
    m_modeGroup->addButton(m_cartTab, 0);
    m_modeGroup->addButton(m_jointTab, 1);
    for (auto* tab : { m_cartTab, m_jointTab }) {
        tab->setCheckable(true);
        tab->setCursor(Qt::PointingHandCursor);
        tab->setStyleSheet(segmentedStyle(false));
        segRow->addWidget(tab, 1);
    }
    m_cartTab->setChecked(true);
    bodyColumn->addWidget(m_modeSwitcher);

    // 控制盘
    m_pad = new QStackedWidget;
    m_cartPad = buildCartPad();
    m_jointPad = buildJointPad();
    m_waitPad = buildWaitPad();
    m_photoPad = buildPhotoPad();
    m_pad->addWidget(m_cartPad);
    m_pad->addWidget(m_jointPad);
    m_pad->addWidget(m_waitPad);
    m_pad->addWidget(m_photoPad);
    bodyColumn->addWidget(m_pad);
    bodyColumn->addWidget(buildStepSetting());
    bodyColumn->addStretch(1);

    scroll->setWidget(body);
    column->addWidget(scroll, 1);

    // 底部：保存 / 运行
    auto* footer = new QFrame;
    footer->setObjectName(QStringLiteral("rpFooter"));
    footer->setStyleSheet(QStringLiteral(
        "QFrame#rpFooter { background:#fafafa; border:none;"
        " border-bottom-left-radius:8px; border-bottom-right-radius:8px;"
        " border-top:1px solid #eeeeee; }"));
    auto* footerColumn = new QVBoxLayout(footer);
    footerColumn->setContentsMargins(15, 12, 15, 12);
    footerColumn->setSpacing(10);

    m_saveButton = new QPushButton(QStringLiteral("💾 保存当前节点修改"));
    m_saveButton->setObjectName(QStringLiteral("robot_program_save"));
    m_saveButton->setCursor(Qt::PointingHandCursor);
    m_saveButton->setMinimumHeight(42);
    m_saveButton->setStyleSheet(QStringLiteral(
        "QPushButton { background:%1; color:#ffffff; border:none;"
        " border-radius:4px; padding:12px; font-size:15px;"
        " font-weight:bold; }"
        "QPushButton:hover:enabled { background:#ffc53d; }"
        "QPushButton:disabled { background:#fffbe6; color:#d4b106; }")
        .arg(kWarning));
    m_saveButton->hide();
    footerColumn->addWidget(m_saveButton);

    auto* runRow = new QHBoxLayout;
    runRow->setSpacing(10);
    m_runSelectedButton = new QPushButton(QStringLiteral("▶ 运行当前节点"));
    m_runSelectedButton->setObjectName(QStringLiteral("robot_program_run_one"));
    m_runSelectedButton->setCursor(Qt::PointingHandCursor);
    m_runSelectedButton->setMinimumHeight(44);
    m_runSelectedButton->setStyleSheet(
        runButtonStyle(kPrimary, "#40a9ff"));
    m_runAllButton = new QPushButton(QStringLiteral("▶ 运行列表"));
    m_runAllButton->setObjectName(QStringLiteral("robot_program_run_all"));
    m_runAllButton->setCursor(Qt::PointingHandCursor);
    m_runAllButton->setMinimumHeight(44);
    m_runAllButton->setStyleSheet(runButtonStyle(kSuccess, "#73d13d"));
    runRow->addWidget(m_runSelectedButton, 1);
    runRow->addWidget(m_runAllButton, 1);
    footerColumn->addLayout(runRow);
    column->addWidget(footer);

    connect(m_cartTab, &QPushButton::clicked, this,
            [this]() { onModeChanged(0); });
    connect(m_jointTab, &QPushButton::clicked, this,
            [this]() { onModeChanged(1); });
    connect(m_captureButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onCapturePose);
    connect(m_cancelEditButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onCancelEdit);
    connect(m_saveButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onSaveNode);
    connect(m_runSelectedButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onRunSelected);
    connect(m_runAllButton, &QPushButton::clicked, this,
            &RobotProgramPanel::onRunAll);

    applyCardShadow(card);
    return card;
}

QWidget* RobotProgramPanel::buildCartPad()
{
    auto* page = new QWidget;
    page->setStyleSheet(QStringLiteral("background:transparent;"));
    auto* column = new QVBoxLayout(page);
    column->setContentsMargins(0, 0, 0, 0);
    column->setSpacing(12);

    auto* positionTitle = new QLabel(QStringLiteral("位置 (mm)"));
    positionTitle->setStyleSheet(sectionTitleStyle());
    column->addWidget(positionTitle);

    const char* names[6] = { "X", "Y", "Z", "RX", "RY", "RZ" };
    for (int i = 0; i < 6; ++i) {
        if (i == 3) {
            column->addSpacing(8);
            auto* directionTitle = new QLabel(QStringLiteral("方向 (°)"));
            directionTitle->setStyleSheet(sectionTitleStyle());
            column->addWidget(directionTitle);
        }
        auto* row = new QHBoxLayout;
        row->setSpacing(10);
        auto* name = textLabel(QString::fromLatin1(names[i]), 15, "#555555",
                               true);
        name->setFixedWidth(28);
        row->addWidget(name);

        m_cartMinus[i] = new RepeatButton;
        m_cartMinus[i]->setText(QStringLiteral("-"));
        m_cartPlus[i] = new RepeatButton;
        m_cartPlus[i]->setText(QStringLiteral("+"));
        for (auto* button : { m_cartMinus[i], m_cartPlus[i] }) {
            button->setFixedSize(55, 42);
            button->setCursor(Qt::PointingHandCursor);
            button->setStyleSheet(axisButtonStyle());
            button->setAutoRepeat(false);
        }

        m_cartEdits[i] = new QLineEdit;
        m_cartEdits[i]->setAlignment(Qt::AlignCenter);
        m_cartEdits[i]->setFixedHeight(42);
        m_cartEdits[i]->setStyleSheet(cartEditStyle());
        m_cartEdits[i]->setReadOnly(true);
        m_cartEdits[i]->setText(QStringLiteral("0.00"));

        // 顺序：[-] [值] [+]
        row->addWidget(m_cartMinus[i]);
        row->addWidget(m_cartEdits[i], 1);
        row->addWidget(m_cartPlus[i]);

        const int axis = i;
        connect(m_cartMinus[i], &QPushButton::clicked, this,
                [this, axis]() { onCartStep(axis, -1); });
        connect(m_cartPlus[i], &QPushButton::clicked, this,
                [this, axis]() { onCartStep(axis, +1); });
        connect(m_cartEdits[i], &QLineEdit::editingFinished, this,
                [this, axis]() { commitDraftCart(axis); });
        column->addLayout(row);
    }
    return page;
}

QWidget* RobotProgramPanel::buildJointPad()
{
    auto* page = new QWidget;
    page->setStyleSheet(QStringLiteral("background:transparent;"));
    auto* column = new QVBoxLayout(page);
    column->setContentsMargins(0, 0, 0, 0);
    column->setSpacing(12);

    const char* names[6] = { "机座", "肩部", "肘部",
                             "手腕1", "手腕2", "手腕3" };
    for (int i = 0; i < 6; ++i) {
        auto* row = new QHBoxLayout;
        row->setSpacing(8);
        auto* name =
            textLabel(QString::fromUtf8(names[i]), 13, "#555555", true);
        name->setFixedWidth(42);
        row->addWidget(name);

        m_jointMinus[i] = new RepeatButton;
        m_jointMinus[i]->setText(QStringLiteral("-"));
        m_jointPlus[i] = new RepeatButton;
        m_jointPlus[i]->setText(QStringLiteral("+"));
        for (auto* button : { m_jointMinus[i], m_jointPlus[i] }) {
            button->setFixedSize(32, 32);
            button->setCursor(Qt::PointingHandCursor);
            button->setStyleSheet(jointButtonStyle());
            row->addWidget(button);
        }

        m_jointSliders[i] = new QSlider(Qt::Horizontal);
        m_jointSliders[i]->setRange(-180, 180);
        m_jointSliders[i]->setPageStep(5);
        m_jointSliders[i]->setStyleSheet(sliderStyle());
        row->addWidget(m_jointSliders[i], 1);

        m_jointEdits[i] = new QLineEdit(QStringLiteral("0.0"));
        m_jointEdits[i]->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
        m_jointEdits[i]->setFixedWidth(60);
        m_jointEdits[i]->setStyleSheet(jointEditStyle());
        m_jointEdits[i]->setReadOnly(true);
        row->addWidget(m_jointEdits[i]);
        row->addWidget(textLabel(QStringLiteral("°"), 13, kTextSub));

        const int axis = i;
        connect(m_jointMinus[i], &QPushButton::clicked, this,
                [this, axis]() { onJointStep(axis, -1); });
        connect(m_jointPlus[i], &QPushButton::clicked, this,
                [this, axis]() { onJointStep(axis, +1); });
        connect(m_jointSliders[i], &QSlider::sliderMoved, this,
                [this, axis](int value) { onJointSliderMoved(axis, value); });
        connect(m_jointSliders[i], &QSlider::sliderReleased, this,
                [this, axis]() {
                    onJointSliderReleased(axis, m_jointSliders[axis]->value());
                });
        connect(m_jointEdits[i], &QLineEdit::editingFinished, this,
                [this, axis]() { commitDraftJoint(axis); });

        column->addLayout(row);
    }
    return page;
}

QWidget* RobotProgramPanel::buildWaitPad()
{
    auto* page = new QWidget;
    page->setStyleSheet(QStringLiteral("background:transparent;"));
    auto* outer = new QVBoxLayout(page);
    outer->setContentsMargins(0, 0, 0, 0);

    auto* box = new QFrame;
    box->setObjectName(QStringLiteral("rpWaitBox"));
    box->setStyleSheet(QStringLiteral(
        "QFrame#rpWaitBox { background:#fafafa; border:1px dashed #d9d9d9;"
        " border-radius:8px; }"));
    auto* column = new QVBoxLayout(box);
    column->setContentsMargins(10, 24, 10, 24);
    column->setSpacing(0);

    auto* title = textLabel(QStringLiteral("⏱ 设置等待时间"), 16, "#555555",
                            true);
    title->setAlignment(Qt::AlignCenter);
    column->addWidget(title);
    column->addSpacing(16);

    auto* row = new QHBoxLayout;
    row->setSpacing(10);
    row->addStretch(1);
    m_editWaitSpin = new QDoubleSpinBox;
    m_editWaitSpin->setRange(0.0, 3600.0);
    m_editWaitSpin->setDecimals(1);
    m_editWaitSpin->setSingleStep(0.5);
    m_editWaitSpin->setValue(1.0);
    m_editWaitSpin->setAlignment(Qt::AlignCenter);
    m_editWaitSpin->setFixedWidth(130);
    m_editWaitSpin->setMinimumHeight(52);
    m_editWaitSpin->setStyleSheet(QStringLiteral(
        "QDoubleSpinBox { font-size:28px; border:1px solid #cccccc;"
        " border-radius:6px; background:#ffffff; padding:6px; }"
        "QDoubleSpinBox:focus { border-color:%1; }")
        .arg(kPrimary));
    row->addWidget(m_editWaitSpin);
    row->addWidget(textLabel(QStringLiteral("秒 (s)"), 18, "#666666"));
    row->addStretch(1);
    column->addLayout(row);

    column->addSpacing(12);
    auto* hint = textLabel(
        QStringLiteral("修改后请点击下方保存按钮"), 12, "#999999");
    hint->setAlignment(Qt::AlignCenter);
    column->addWidget(hint);

    connect(m_editWaitSpin, QOverload<double>::of(&QDoubleSpinBox::valueChanged),
            this, &RobotProgramPanel::onWaitDraftChanged);

    outer->addWidget(box);
    return page;
}

QWidget* RobotProgramPanel::buildPhotoPad()
{
    auto* page = new QWidget;
    page->setStyleSheet(QStringLiteral("background:transparent;"));
    auto* outer = new QVBoxLayout(page);
    outer->setContentsMargins(0, 0, 0, 0);

    auto* box = new QFrame;
    box->setObjectName(QStringLiteral("rpPhotoBox"));
    box->setStyleSheet(QStringLiteral(
        "QFrame#rpPhotoBox { background:#fafafa; border:1px dashed #d9d9d9;"
        " border-radius:8px; }"));
    auto* column = new QVBoxLayout(box);
    column->setContentsMargins(10, 30, 10, 30);
    column->setSpacing(6);

    auto* icon = textLabel(QStringLiteral("📷"), 40, "#666666");
    icon->setAlignment(Qt::AlignCenter);
    column->addWidget(icon);
    auto* title = textLabel(QStringLiteral("拍照采集动作"), 15, "#555555",
                            true);
    title->setAlignment(Qt::AlignCenter);
    column->addWidget(title);
    auto* hint = textLabel(QStringLiteral("该节点无需额外参数配置"), 13,
                           "#999999");
    hint->setAlignment(Qt::AlignCenter);
    column->addWidget(hint);

    outer->addWidget(box);
    return page;
}

QWidget* RobotProgramPanel::buildStepSetting()
{
    auto* frame = new QFrame;
    frame->setObjectName(QStringLiteral("rpStep"));
    frame->setStyleSheet(QStringLiteral(
        "QFrame#rpStep { background:#fafafa; border:1px solid #eeeeee;"
        " border-radius:6px; }"));
    auto* row = new QHBoxLayout(frame);
    row->setContentsMargins(12, 10, 12, 10);
    row->setSpacing(6);
    row->addStretch(1);
    row->addWidget(textLabel(QStringLiteral("当前步进:"), 14, "#555555"));
    m_stepSpin = new QDoubleSpinBox;
    m_stepSpin->setObjectName(QStringLiteral("robot_program_step"));
    m_stepSpin->setRange(JogPolicy::MIN_STEP, JogPolicy::MAX_STEP);
    m_stepSpin->setDecimals(2);
    m_stepSpin->setValue(1.0);
    m_stepSpin->setFixedWidth(78);
    m_stepSpin->setMinimumHeight(32);
    m_stepSpin->setAlignment(Qt::AlignCenter);
    m_stepSpin->setStyleSheet(smallInputStyle());
    row->addWidget(m_stepSpin);
    row->addWidget(textLabel(QStringLiteral("mm / °"), 12, "#999999"));
    row->addStretch(1);
    return frame;
}

void RobotProgramPanel::setController(RobotProgramController* controller)
{
    if (m_controller == controller)
        return;
    if (m_controller)
        QObject::disconnect(m_controller, nullptr, this, nullptr);
    m_controller = controller;
    if (!m_controller) {
        m_selectedIndex = -1;
        m_selectedId.clear();
        m_editDirty = false;
        refreshNodes();
        refreshPadValues();
        refreshActions();
        return;
    }
    bindController();
}

void RobotProgramPanel::bindController()
{
    {
        const QSignalBlocker blocker(m_backendCombo);
        m_backendCombo->setCurrentIndex(
            m_controller->backendKind()
                    == RobotProgramController::BackendKind::Ur
                ? 1 : 0);
    }
    syncAddressFields();
    m_controller->setJogSpeed(m_speedSlider->value());

    connect(m_controller, &RobotProgramController::backendChanged, this,
            [this]() {
                if (!m_controller)
                    return;
                const QSignalBlocker blocker(m_backendCombo);
                m_backendCombo->setCurrentIndex(
                    m_controller->backendKind()
                            == RobotProgramController::BackendKind::Ur
                        ? 1 : 0);
                syncAddressFields();
                m_selectedIndex = -1;
                m_selectedId.clear();
                m_editDirty = false;
                m_runningIndex = -1;
                m_state = m_controller->backend()->state();
                updatePose(m_state);
                setConnected(m_controller->backend()->isConnected());
                setEnabled(m_controller->backend()->isEnabled());
                refreshNodes();
            });
    connect(m_controller, &RobotProgramController::connectedChanged, this,
            &RobotProgramPanel::setConnected);
    connect(m_controller, &RobotProgramController::enabledChanged, this,
            &RobotProgramPanel::setEnabled);
    connect(m_controller, &RobotProgramController::poseUpdated, this,
            &RobotProgramPanel::updatePose);
    connect(m_controller, &RobotProgramController::statusMessage, this,
            [this](const QString& text, bool error) {
                showToast(text, error);
                log(text, error);
            });
    connect(m_controller, &RobotProgramController::programChanged, this,
            [this]() { refreshNodes(); });
    connect(m_controller, &RobotProgramController::runnerStateChanged, this,
            &RobotProgramPanel::onRunnerState);
    connect(m_controller, &RobotProgramController::nodeStarted, this,
            [this](int index) {
                m_runningIndex = index;
                refreshRowStyles();
                if (m_controller) {
                    const auto& nodes = m_controller->program().nodes;
                    if (index >= 0
                        && index < static_cast<int>(nodes.size())) {
                        const auto& payload =
                            nodes[static_cast<std::size_t>(index)].payload;
                        log(QStringLiteral("执行第 %1 个节点：%2 %3")
                                .arg(index + 1)
                                .arg(RobotProgram::kindLabel(
                                    RobotProgram::kindOf(payload)))
                                .arg(RobotProgram::displayTitle(payload)));
                    }
                }
                if (index >= 0 && index < m_nodeRows.size()) {
                    m_listScroll->ensureWidgetVisible(m_nodeRows[index], 0, 20);
                }
                refreshActions();
            });
    connect(m_controller, &RobotProgramController::nodeFinished, this,
            [this](int index, bool ok, const QString& error) {
                if (ok) {
                    log(QStringLiteral("第 %1 个节点完成").arg(index + 1));
                } else {
                    showToast(QStringLiteral("第 %1 个节点失败：%2")
                                  .arg(index + 1).arg(error), true);
                    log(QStringLiteral("第 %1 个节点失败：%2")
                            .arg(index + 1).arg(error), true);
                }
            });
    connect(m_controller, &RobotProgramController::runFinished, this,
            [this](bool ok, const QString& error) {
                if (ok) {
                    showToast(QStringLiteral("列表运行完成"));
                    log(QStringLiteral("程序运行完成"));
                } else if (error != QStringLiteral("已停止")) {
                    showToast(QStringLiteral("程序运行失败：%1").arg(error),
                              true);
                    log(QStringLiteral("程序运行失败：%1").arg(error), true);
                } else {
                    showToast(QStringLiteral("已停止"));
                }
                refreshActions();
            });
    connect(m_controller, &RobotProgramController::photoStarted, this,
            [this]() {
                showToast(QStringLiteral("拍照节点：采集链路运行中…"));
            });

    m_state = m_controller->backend()->state();
    updatePose(m_state);
    setConnected(m_controller->backend()->isConnected());
    setEnabled(m_controller->backend()->isEnabled());
    onRunnerState(m_controller->runner()->state());
    refreshNodes();
}

// ── 节点列表 ─────────────────────────────────────────────────────────

void RobotProgramPanel::refreshNodes()
{
    if (!m_listLayout)
        return;

    while (QLayoutItem* item = m_listLayout->takeAt(0)) {
        if (QWidget* widget = item->widget())
            delete widget;
        delete item;
    }
    m_nodeRows.clear();

    if (!m_controller) {
        m_countLabel->setText(QStringLiteral("共 0 个节点"));
        auto* hint = textLabel(QStringLiteral("控制端未接入"), 14, "#bfbfbf");
        hint->setAlignment(Qt::AlignCenter);
        m_listLayout->addSpacing(40);
        m_listLayout->addWidget(hint);
        m_listLayout->addStretch(1);
        m_selectedIndex = -1;
        m_selectedId.clear();
        applyEditMode();
        return;
    }

    const auto& nodes = m_controller->program().nodes;
    m_countLabel->setText(
        QStringLiteral("共 %1 个节点").arg(static_cast<int>(nodes.size())));

    if (nodes.empty()) {
        auto* empty = textLabel(QStringLiteral("暂无节点，请先添加动作。"),
                                14, "#bfbfbf");
        empty->setAlignment(Qt::AlignCenter);
        m_listLayout->addSpacing(50);
        m_listLayout->addWidget(empty);
        m_listLayout->addStretch(1);
    } else {
        for (std::size_t i = 0; i < nodes.size(); ++i) {
            const auto& node = nodes[i];
            const auto kind = RobotProgram::kindOf(node.payload);
            const int index = static_cast<int>(i);

            auto* row = new NodeRowFrame([this, index]() { selectNode(index); });
            row->setObjectName(QStringLiteral("rpNodeRow"));
            row->setFixedHeight(46);
            row->setStyleSheet(nodeRowStyle(false, false));
            auto* rowLayout = new QHBoxLayout(row);
            rowLayout->setContentsMargins(12, 0, 12, 0);
            rowLayout->setSpacing(8);

            auto* indexLabel = textLabel(
                QStringLiteral("%1.").arg(index + 1), 13, "#999999", true);
            indexLabel->setFixedWidth(20);
            rowLayout->addWidget(indexLabel);

            auto* tag = new QLabel(RobotProgram::kindLabel(kind));
            tag->setStyleSheet(tagStyle(kind));
            tag->setAlignment(Qt::AlignCenter);
            rowLayout->addWidget(tag);

            rowLayout->addWidget(textLabel(
                RobotProgram::displayTitle(node.payload), 13, kTextMain));

            auto* detail = new ElideLabel;
            detail->setStyleSheet(QStringLiteral(
                "font-size:12px;color:#666666;font-family:Consolas,monospace;"
                "background:transparent;"));
            detail->setFullText(RobotProgram::displayDetail(node.payload));
            rowLayout->addWidget(detail, 1);

            m_nodeRows.push_back(row);
            m_listLayout->addWidget(row);
        }
        m_listLayout->addStretch(1);
    }

    // 保留选中项（用稳定 id 找新下标）；节点被删掉就退出编辑模式。
    if (!m_selectedId.isEmpty()) {
        int found = -1;
        for (int i = 0; i < static_cast<int>(nodes.size()); ++i) {
            if (nodes[static_cast<std::size_t>(i)].id == m_selectedId) {
                found = i;
                break;
            }
        }
        if (found >= 0) {
            m_selectedIndex = found;
        } else {
            m_selectedIndex = -1;
            m_selectedId.clear();
            m_editDirty = false;
        }
    } else {
        m_selectedIndex = -1;
    }

    refreshRowStyles();
    applyEditMode();
}

void RobotProgramPanel::refreshRowStyles()
{
    for (int i = 0; i < m_nodeRows.size(); ++i) {
        m_nodeRows[i]->setStyleSheet(
            nodeRowStyle(i == m_selectedIndex, i == m_runningIndex));
    }
}

// ── 编辑模式 ─────────────────────────────────────────────────────────

bool RobotProgramPanel::isEditing() const
{
    if (!m_controller || m_selectedIndex < 0)
        return false;
    return m_selectedIndex
        < static_cast<int>(m_controller->program().nodes.size());
}

RobotProgram::NodeKind RobotProgramPanel::selectedKind() const
{
    if (!isEditing())
        return RobotProgram::NodeKind::Move;
    return RobotProgram::kindOf(
        m_controller->program()
            .nodes[static_cast<std::size_t>(m_selectedIndex)]
            .payload);
}

void RobotProgramPanel::selectNode(int index)
{
    if (!m_controller || m_running)
        return;
    const auto& nodes = m_controller->program().nodes;
    if (index < 0 || index >= static_cast<int>(nodes.size()))
        return;
    const auto& payload = nodes[static_cast<std::size_t>(index)].payload;
    m_selectedIndex = index;
    m_selectedId = nodes[static_cast<std::size_t>(index)].id;
    m_editDirty = false;

    if (const auto* move = std::get_if<RobotProgram::MoveNode>(&payload)) {
        m_draftSpace = move->space;
        m_draftPose = move->target;
        m_jointMode = move->space == RobotProgram::MoveNode::Space::Joint;
    } else if (const auto* wait =
                   std::get_if<RobotProgram::WaitNode>(&payload)) {
        m_draftSeconds = wait->seconds;
    }

    refreshRowStyles();
    applyEditMode();
}

void RobotProgramPanel::clearSelection()
{
    m_selectedIndex = -1;
    m_selectedId.clear();
    m_editDirty = false;
    refreshRowStyles();
    applyEditMode();
}

void RobotProgramPanel::applyEditMode()
{
    if (!m_editBanner)
        return;
    const bool editing = isEditing();
    m_editBanner->setVisible(editing);
    m_commSection->setVisible(!editing);
    m_modeSwitcher->setVisible(!editing);
    m_saveButton->setVisible(editing);

    if (editing) {
        const auto kind = selectedKind();
        m_editBannerText->setText(
            QStringLiteral("正在编辑: 节点 %1 (%2)")
                .arg(m_selectedIndex + 1)
                .arg(RobotProgram::kindLabel(kind)));
        m_captureButton->setVisible(kind == RobotProgram::NodeKind::Move);
        m_saveButton->setText(
            QStringLiteral("💾 保存节点 %1 的修改").arg(m_selectedIndex + 1));

        if (kind == RobotProgram::NodeKind::Move) {
            m_pad->setCurrentWidget(
                m_draftSpace == RobotProgram::MoveNode::Space::Joint
                    ? m_jointPad : m_cartPad);
        } else if (kind == RobotProgram::NodeKind::Wait) {
            m_pad->setCurrentWidget(m_waitPad);
        } else {
            m_pad->setCurrentWidget(m_photoPad);
        }
    } else {
        m_pad->setCurrentWidget(m_jointMode ? m_jointPad : m_cartPad);
    }

    // 编辑关节节点会把当前模式切到关节；取消编辑后分段控件的选中态要跟上。
    m_cartTab->setStyleSheet(segmentedStyle(!m_jointMode));
    m_jointTab->setStyleSheet(segmentedStyle(m_jointMode));
    {
        const QSignalBlocker cartBlocker(m_cartTab);
        const QSignalBlocker jointBlocker(m_jointTab);
        m_cartTab->setChecked(!m_jointMode);
        m_jointTab->setChecked(m_jointMode);
    }

    refreshPadValues();
    refreshActions();
}

void RobotProgramPanel::setDraftDirty(bool dirty)
{
    m_editDirty = dirty;
    refreshActions();
}

void RobotProgramPanel::commitDraftCart(int axis)
{
    if (!isEditing() || selectedKind() != RobotProgram::NodeKind::Move
        || m_draftSpace != RobotProgram::MoveNode::Space::Cartesian
        || !JogPolicy::validAxis(axis)) {
        return;
    }
    bool ok = false;
    const double value = m_cartEdits[axis]->text().trimmed().toDouble(&ok);
    if (!ok || !std::isfinite(value)) {
        refreshPadValues();
        return;
    }
    m_draftPose[static_cast<std::size_t>(axis)] = value;
    m_cartEdits[axis]->setText(number2(value));
    setDraftDirty(true);
}

void RobotProgramPanel::commitDraftJoint(int axis)
{
    if (!isEditing() || selectedKind() != RobotProgram::NodeKind::Move
        || m_draftSpace != RobotProgram::MoveNode::Space::Joint
        || !JogPolicy::validAxis(axis)) {
        return;
    }
    bool ok = false;
    const double value = m_jointEdits[axis]->text().trimmed().toDouble(&ok);
    if (!ok || !std::isfinite(value)) {
        refreshPadValues();
        return;
    }
    const double clamped = JogPolicy::clampJoint(value);
    m_draftPose[static_cast<std::size_t>(axis)] = clamped;
    m_jointEdits[axis]->setText(number1(clamped));
    setDraftDirty(true);
}

void RobotProgramPanel::onCapturePose()
{
    if (!isEditing() || selectedKind() != RobotProgram::NodeKind::Move)
        return;
    if (!m_connected) {
        showToast(QStringLiteral("请先连接机器人，才能读取当前位姿"), true);
        return;
    }
    m_draftPose = m_draftSpace == RobotProgram::MoveNode::Space::Joint
        ? m_state.joint : m_state.cart;
    m_editDirty = true;
    refreshPadValues();
    refreshActions();
    showToast(QStringLiteral("已载入当前位姿，保存后生效"));
}

void RobotProgramPanel::onSaveNode()
{
    if (!isEditing() || m_running)
        return;
    const int index = m_selectedIndex;
    const int shown = index + 1;
    const auto kind = selectedKind();

    // 先退出编辑，避免 controller 同步发出的 programChanged 继续保留选中态。
    m_selectedIndex = -1;
    m_selectedId.clear();
    m_editDirty = false;

    bool ok = false;
    if (kind == RobotProgram::NodeKind::Move) {
        ok = m_controller->updateMoveTarget(index, m_draftPose);
    } else if (kind == RobotProgram::NodeKind::Wait) {
        ok = m_controller->updateWaitSeconds(index, m_draftSeconds);
    } else {
        ok = true;   // 拍照节点没有可保存参数
    }

    refreshRowStyles();
    applyEditMode();
    showToast(ok ? QStringLiteral("节点 %1 修改已保存").arg(shown)
                 : QStringLiteral("保存失败：程序正在运行"),
              !ok);
}

void RobotProgramPanel::onCancelEdit()
{
    if (!isEditing())
        return;
    const int index = m_selectedIndex;
    clearSelection();
    if (index >= 0)
        showToast(QStringLiteral("已取消编辑"));
}

// ── 状态刷新 ─────────────────────────────────────────────────────────

void RobotProgramPanel::refreshPadValues()
{
    if (!m_cartEdits[0])
        return;

    const bool editingMove =
        isEditing() && selectedKind() == RobotProgram::NodeKind::Move;
    const bool editCart = editingMove
        && m_draftSpace == RobotProgram::MoveNode::Space::Cartesian;
    const bool editJoint = editingMove
        && m_draftSpace == RobotProgram::MoveNode::Space::Joint;

    for (int i = 0; i < 6; ++i) {
        const auto idx = static_cast<std::size_t>(i);
        const double cartValue = editCart ? m_draftPose[idx] : m_state.cart[idx];
        if (!m_cartEdits[i]->hasFocus())
            m_cartEdits[i]->setText(number2(cartValue));
        m_cartEdits[i]->setReadOnly(!editCart);

        const double jointValue =
            editJoint ? m_draftPose[idx] : m_state.joint[idx];
        if (!m_jointEdits[i]->hasFocus())
            m_jointEdits[i]->setText(number1(jointValue));
        m_jointEdits[i]->setReadOnly(!editJoint);

        if (!m_jointSliders[i]->isSliderDown()) {
            const QSignalBlocker blocker(m_jointSliders[i]);
            m_jointSliders[i]->setValue(std::clamp(
                static_cast<int>(std::lround(jointValue)), -180, 180));
        }
    }

    if (m_editWaitSpin && isEditing()
        && selectedKind() == RobotProgram::NodeKind::Wait) {
        const QSignalBlocker blocker(m_editWaitSpin);
        m_editWaitSpin->setValue(m_draftSeconds);
    }
}

void RobotProgramPanel::refreshActions()
{
    if (!m_addMoveButton)
        return;

    const bool bound = m_controller != nullptr;
    const bool running = m_running;
    const bool editing = isEditing();
    const bool canControl = bound && m_connected && m_enabled && !running;
    const bool canEdit = editing && !running;
    const auto kind = selectedKind();
    const bool editingMove = canEdit && kind == RobotProgram::NodeKind::Move;
    const bool editCart = editingMove
        && m_draftSpace == RobotProgram::MoveNode::Space::Cartesian;
    const bool editJoint = editingMove
        && m_draftSpace == RobotProgram::MoveNode::Space::Joint;
    const bool padCart = canControl || editCart;
    const bool padJoint = canControl || editJoint;
    const bool urBackend = m_backendCombo && m_backendCombo->currentIndex() == 1;

    m_addMoveButton->setEnabled(canControl);
    m_addPhotoButton->setEnabled(canControl);
    m_addWaitButton->setEnabled(canControl);

    m_deleteButton->setEnabled(canEdit);
    m_saveButton->setEnabled(canEdit && kind != RobotProgram::NodeKind::Photo
                             && m_editDirty);
    m_captureButton->setEnabled(editingMove && m_connected);
    m_cancelEditButton->setEnabled(canEdit);

    m_runSelectedButton->setEnabled(canControl && editing);
    m_runAllButton->setEnabled(
        canControl && !m_controller->program().nodes.empty());

    m_enableButton->setEnabled(bound && m_connected && !running);
    {
        const QSignalBlocker blocker(m_enableButton);
        m_enableButton->setChecked(m_enabled);
    }
    m_enableButton->setText(m_enabled ? QStringLiteral("⚡ 已使能")
                                      : QStringLiteral("⚡ 开启使能"));
    m_stopButton->setEnabled(bound && (m_connected || running));

    m_connectButton->setEnabled(bound && !running);
    m_connectButton->setText(m_connected ? QStringLiteral("🔌 断开连接")
                                         : QStringLiteral("🔌 连接"));
    m_backendCombo->setEnabled(bound && !running);
    const bool addressEditable = urBackend && !m_connected && !running;
    m_hostEdit->setEnabled(addressEditable);
    m_portSpin->setEnabled(addressEditable);

    m_speedSlider->setEnabled(bound && m_connected && !running);

    for (int i = 0; i < 6; ++i) {
        m_cartMinus[i]->setEnabled(padCart);
        m_cartPlus[i]->setEnabled(padCart);
        m_jointMinus[i]->setEnabled(padJoint);
        m_jointPlus[i]->setEnabled(padJoint);
        m_jointSliders[i]->setEnabled(padJoint);
    }

    m_stepSpin->setEnabled(
        bound && !running
        && (!editing || kind == RobotProgram::NodeKind::Move));
    if (m_editWaitSpin)
        m_editWaitSpin->setEnabled(
            canEdit && kind == RobotProgram::NodeKind::Wait);

    const bool modeEnabled = bound && !running && !editing;
    m_cartTab->setEnabled(modeEnabled);
    m_jointTab->setEnabled(modeEnabled);
}

void RobotProgramPanel::updatePose(const RobotMotion::State& state)
{
    m_state = state;
    // 编辑中显示的是节点草稿，不能被 125 Hz 的实时位姿覆盖。
    if (isEditing())
        return;
    refreshPadValues();
}

void RobotProgramPanel::setConnected(bool connected)
{
    m_connected = connected;
    if (!connected)
        m_enabled = false;
    m_statusDot->setStyleSheet(
        QStringLiteral("background:%1;border-radius:6px;")
            .arg(connected ? kSuccess : kBorder));
    m_connLabel->setText(connected ? QStringLiteral("通信已连接")
                                   : QStringLiteral("通信未连接"));
    refreshActions();
}

void RobotProgramPanel::setEnabled(bool enabled)
{
    m_enabled = enabled;
    refreshActions();
}

void RobotProgramPanel::onRunnerState(ProgramRunner::State state)
{
    m_running = state != ProgramRunner::State::Idle;
    if (!m_running)
        m_runningIndex = -1;
    refreshRowStyles();
    refreshActions();
}

void RobotProgramPanel::showToast(const QString& text, bool error)
{
    if (!m_toast || text.isEmpty())
        return;
    m_toast->setStyleSheet(
        error
            ? QStringLiteral("QLabel { background:rgba(160,20,20,215);"
                             " color:#ffffff; padding:10px 24px;"
                             " border-radius:4px; font-size:14px; }")
            : QStringLiteral("QLabel { background:rgba(0,0,0,190);"
                             " color:#ffffff; padding:10px 24px;"
                             " border-radius:4px; font-size:14px; }"));
    m_toast->setText(text);
    m_toast->adjustSize();
    const int x = std::max(10, (width() - m_toast->width()) / 2);
    m_toast->move(x, 20);
    m_toast->show();
    m_toast->raise();
    if (m_toastTimer)
        m_toastTimer->start(error ? 4800 : 2200);
}

void RobotProgramPanel::log(const QString& text, bool error)
{
    emit logMessage(QStringLiteral("[机器人控制台] %1").arg(text));
    Q_UNUSED(error);
}

void RobotProgramPanel::syncAddressFields()
{
    if (!m_backendCombo)
        return;
    const bool ur = m_backendCombo->currentIndex() == 1;
    const bool editable = ur && !m_connected && !m_running;
    if (m_hostEdit)
        m_hostEdit->setEnabled(editable);
    if (m_portSpin)
        m_portSpin->setEnabled(editable);
}

// ── 动作 ─────────────────────────────────────────────────────────────

void RobotProgramPanel::onBackendKindChanged(int index)
{
    const auto kind = index == 1
        ? RobotProgramController::BackendKind::Ur
        : RobotProgramController::BackendKind::Simulated;
    if (m_controller && m_controller->backendKind() != kind) {
        m_controller->setBackendKind(kind);
        m_portSpin->setValue(RobotProgramController::defaultPort(kind));
        if (m_hostEdit->text().trimmed().isEmpty()) {
            m_hostEdit->setText(RobotProgramController::defaultHost(kind));
        }
    }
    syncAddressFields();
}

void RobotProgramPanel::onConnectClicked()
{
    if (!m_controller)
        return;
    if (m_connected) {
        m_controller->disconnectDevice();
        return;
    }
    QString host = m_hostEdit->text().trimmed();
    if (host.isEmpty()) {
        host = RobotProgramController::defaultHost(m_controller->backendKind());
        m_hostEdit->setText(host);
    }
    m_controller->connectDevice(
        host, static_cast<quint16>(m_portSpin->value()));
}

void RobotProgramPanel::onEnableToggled(bool on)
{
    if (!m_controller)
        return;
    // 后端状态是权威值（UR 走工作线程，异步回来）；这里不能回读后立刻
    // 改按钮，否则真机被误判为拒绝。
    m_controller->setEnabled(on);
}

void RobotProgramPanel::onStopClicked()
{
    if (!m_controller)
        return;
    m_controller->stop();
    showToast(QStringLiteral("停止指令已发出"));
}

void RobotProgramPanel::onAddMove()
{
    if (!m_controller || m_running)
        return;
    if (!m_connected || !m_enabled) {
        showToast(QStringLiteral("请先连接并使能机器人"), true);
        return;
    }
    RobotProgram::MoveNode move;
    move.space = m_jointMode ? RobotProgram::MoveNode::Space::Joint
                             : RobotProgram::MoveNode::Space::Cartesian;
    move.target = m_jointMode ? m_state.joint : m_state.cart;
    move.speedPct = m_speedSlider->value();
    m_controller->addNode(move);
    showToast(QStringLiteral("已添加移动节点"));
}

void RobotProgramPanel::onAddPhoto()
{
    if (!m_controller || m_running)
        return;
    if (!m_connected || !m_enabled) {
        showToast(QStringLiteral("请先连接并使能机器人"), true);
        return;
    }
    RobotProgram::PhotoNode photo;
    photo.autoSave = true;
    m_controller->addNode(photo);
    showToast(QStringLiteral("已添加拍照节点"));
}

void RobotProgramPanel::onAddWait()
{
    if (!m_controller || m_running)
        return;
    if (!m_connected || !m_enabled) {
        showToast(QStringLiteral("请先连接并使能机器人"), true);
        return;
    }

    QDialog dialog(this);
    dialog.setWindowTitle(QStringLiteral("设置等待时间"));
    dialog.setModal(true);
    dialog.setMinimumWidth(320);
    dialog.setStyleSheet(QStringLiteral(
        "QDialog { background:#ffffff; }"
        "QLabel { color:#333333; }"));
    auto* column = new QVBoxLayout(&dialog);
    column->setContentsMargins(20, 20, 20, 20);
    column->setSpacing(16);
    auto* title = textLabel(QStringLiteral("⏱ 设置等待时间"), 16, kTextMain,
                            true);
    title->setAlignment(Qt::AlignCenter);
    column->addWidget(title);

    auto* row = new QHBoxLayout;
    row->setSpacing(10);
    row->addStretch(1);
    auto* spin = new QDoubleSpinBox;
    spin->setRange(0.0, 3600.0);
    spin->setDecimals(1);
    spin->setSingleStep(0.5);
    spin->setValue(1.0);
    spin->setFixedWidth(110);
    spin->setMinimumHeight(46);
    spin->setAlignment(Qt::AlignCenter);
    spin->setStyleSheet(QStringLiteral(
        "QDoubleSpinBox { font-size:20px; border:1px solid #cccccc;"
        " border-radius:4px; padding:8px; background:#ffffff; }"
        "QDoubleSpinBox:focus { border-color:%1; }")
        .arg(kPrimary));
    row->addWidget(spin);
    row->addWidget(textLabel(QStringLiteral("秒 (s)"), 14, "#666666"));
    row->addStretch(1);
    column->addLayout(row);

    auto* buttons = new QHBoxLayout;
    buttons->setSpacing(10);
    auto* cancel = new QPushButton(QStringLiteral("取消"));
    auto* confirm = new QPushButton(QStringLiteral("确认添加"));
    cancel->setMinimumHeight(36);
    confirm->setMinimumHeight(36);
    cancel->setStyleSheet(outlineButtonStyle(false));
    confirm->setStyleSheet(QStringLiteral(
        "QPushButton { background:%1; color:#ffffff; border:none;"
        " border-radius:4px; padding:8px 16px; font-size:14px;"
        " font-weight:bold; }"
        "QPushButton:hover:enabled { background:#40a9ff; }")
        .arg(kPrimary));
    buttons->addWidget(cancel, 1);
    buttons->addWidget(confirm, 1);
    column->addLayout(buttons);

    connect(cancel, &QPushButton::clicked, &dialog, &QDialog::reject);
    connect(confirm, &QPushButton::clicked, &dialog, &QDialog::accept);

    if (dialog.exec() != QDialog::Accepted)
        return;

    RobotProgram::WaitNode wait;
    wait.seconds = spin->value();
    m_controller->addNode(wait);
    showToast(QStringLiteral("已添加等待节点"));
}

void RobotProgramPanel::onDeleteNode()
{
    if (!m_controller || m_running || !isEditing())
        return;
    const int index = m_selectedIndex;
    m_selectedIndex = -1;
    m_selectedId.clear();
    m_editDirty = false;
    if (m_controller->removeNode(index))
        showToast(QStringLiteral("已删除节点"));
    refreshRowStyles();
    applyEditMode();
}

void RobotProgramPanel::onRunSelected()
{
    if (!m_controller || !isEditing() || m_running)
        return;
    m_controller->runOne(m_selectedIndex);
}

void RobotProgramPanel::onRunAll()
{
    if (!m_controller || m_running)
        return;
    m_controller->runAll();
}

void RobotProgramPanel::onCartStep(int axis, int direction)
{
    if (!JogPolicy::validAxis(axis) || m_running)
        return;
    const double delta = m_stepSpin->value() * direction;

    if (isEditing() && selectedKind() == RobotProgram::NodeKind::Move
        && m_draftSpace == RobotProgram::MoveNode::Space::Cartesian) {
        m_draftPose[static_cast<std::size_t>(axis)] += delta;
        setDraftDirty(true);
        refreshPadValues();
        return;
    }

    if (!m_controller || !m_connected || !m_enabled)
        return;
    m_controller->jog(axis, delta, false);
}

void RobotProgramPanel::onJointStep(int axis, int direction)
{
    if (!JogPolicy::validAxis(axis) || m_running)
        return;
    const double delta = m_stepSpin->value() * direction;

    if (isEditing() && selectedKind() == RobotProgram::NodeKind::Move
        && m_draftSpace == RobotProgram::MoveNode::Space::Joint) {
        m_draftPose[static_cast<std::size_t>(axis)] =
            JogPolicy::clampJoint(
                m_draftPose[static_cast<std::size_t>(axis)] + delta);
        setDraftDirty(true);
        refreshPadValues();
        return;
    }

    if (!m_controller || !m_connected || !m_enabled)
        return;
    m_controller->jog(axis, delta, true);
}

void RobotProgramPanel::onJointSliderMoved(int axis, int value)
{
    if (!JogPolicy::validAxis(axis))
        return;
    if (isEditing() && selectedKind() == RobotProgram::NodeKind::Move
        && m_draftSpace == RobotProgram::MoveNode::Space::Joint) {
        m_draftPose[static_cast<std::size_t>(axis)] = value;
        m_jointEdits[axis]->setText(number1(value));
        setDraftDirty(true);
    } else {
        m_jointEdits[axis]->setText(number1(value));
    }
}

void RobotProgramPanel::onJointSliderReleased(int axis, int value)
{
    if (!JogPolicy::validAxis(axis) || m_running)
        return;
    if (isEditing() && selectedKind() == RobotProgram::NodeKind::Move
        && m_draftSpace == RobotProgram::MoveNode::Space::Joint) {
        m_draftPose[static_cast<std::size_t>(axis)] = value;
        m_jointEdits[axis]->setText(number1(value));
        setDraftDirty(true);
        return;
    }
    if (!m_controller || !m_connected || !m_enabled)
        return;
    m_controller->moveJointAxisTo(axis, value);
}

void RobotProgramPanel::onModeChanged(int id)
{
    if (!m_pad)
        return;
    m_jointMode = (id == 1);
    if (!isEditing())
        m_pad->setCurrentWidget(m_jointMode ? m_jointPad : m_cartPad);
    m_cartTab->setStyleSheet(segmentedStyle(!m_jointMode));
    m_jointTab->setStyleSheet(segmentedStyle(m_jointMode));
    {
        const QSignalBlocker cartBlocker(m_cartTab);
        const QSignalBlocker jointBlocker(m_jointTab);
        m_cartTab->setChecked(!m_jointMode);
        m_jointTab->setChecked(m_jointMode);
    }
    refreshPadValues();
    refreshActions();
}

void RobotProgramPanel::onWaitDraftChanged(double seconds)
{
    if (!isEditing() || selectedKind() != RobotProgram::NodeKind::Wait)
        return;
    m_draftSeconds = seconds;
    setDraftDirty(true);
}
