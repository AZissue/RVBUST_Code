#include "ui/ToolsPanel.h"

#include "logic/GeometryTools.h"
#include "logic/AppConfig.h"
#include "logic/CalibrationService.h"
#include "logic/EfortPoseReader.h"   // splitAddress：埃夫特地址只留 IP
#include "logic/PixelTo3DService.h"
#include "logic/PlyPointReader.h"
#include "logic/RobotDataFormats.h"
#include "logic/ToolInputParser.h"
#include "logic/TransformTools.h"
#include "logic/MeasureMethods.h"
#include "ui/ArrowComboBox.h"
#include "ui/MeasurePage.h"
#include "ui/MeasurePages.h"
#include "ui/Theme.h"

#include <QApplication>
#include <QClipboard>
#include <QCheckBox>
#include <QDir>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QGridLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QHeaderView>   // QTableWidget's header API (incomplete type in QtWidgets)
#include <QImage>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPainter>
#include <QPaintEvent>
#include <QPolygon>
#include <QScrollArea>
#include <QSignalBlocker>
#include <QTextEdit>
#include <QVBoxLayout>
#include <QtConcurrent>
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <string>
#include <vector>

namespace {

using RobotDataFormats::Id;

// 下拉框里的 Id 列表 —— 唯一出处是 RobotDataFormats::ids()。
// 索引与 Id 不相等（常用档里夹着四元数/矩阵），所以一律把 Id 存进 itemData，
// 不许 static_cast(currentIndex())。
std::vector<Id> formatIdsForCombo(bool advanced, bool cardOnly)
{
    std::vector<Id> out;
    for (const Id id : RobotDataFormats::ids(RobotDataFormats::Tier::Common))
        if (!cardOnly || RobotDataFormats::cardUsable(id))
            out.push_back(id);
    if (advanced)
        for (const Id id : RobotDataFormats::ids(RobotDataFormats::Tier::Advanced))
            if (!cardOnly || RobotDataFormats::cardUsable(id))
                out.push_back(id);
    return out;
}

// 重建下拉框，尽量保持当前选中的 Id（勾选「高级」时列表变长，不能跳回第一项）。
void rebuildFormatCombo(QComboBox* combo, bool advanced, bool cardOnly,
                        Id selected)
{
    if (!combo)
        return;
    const QSignalBlocker blocker(combo);
    combo->clear();
    int selectedIndex = -1;
    for (const Id id : formatIdsForCombo(advanced, cardOnly)) {
        combo->addItem(RobotDataFormats::displayName(id), static_cast<int>(id));
        if (id == selected)
            selectedIndex = combo->count() - 1;
    }
    combo->setCurrentIndex(selectedIndex >= 0 ? selectedIndex : 0);
}

Id comboFormat(const QComboBox* combo, Id fallback = Id::EulerSxyz)
{
    if (!combo || combo->currentIndex() < 0)
        return fallback;
    const int raw = combo->currentData().toInt();
    return RobotDataFormats::isValidId(raw) ? static_cast<Id>(raw) : fallback;
}

// 「试算各格式」的候选集：现场真正会遇到的几种。全 24 种 × 单位会让
// 标定板模式重跑几十遍识别，那是「数据格式推算」页转动实验要解决的事，
// 不该塞进这个按钮。顺序 = 先常见约定，再轴角。
const std::vector<Id> kTryAllPoseFormats {
    Id::EulerSxyz, Id::EulerRzyx, Id::EulerRzyz, Id::EulerRxyz,
    Id::RotationVector,
};

// 推算页的输入：允许只贴 3 个旋转数，也允许贴整行 6 个数（只取后 3 个）。
bool parseRotationTriple(const QString& text, std::array<double, 3>& out)
{
    const std::string raw = text.toStdString();
    auto r = ToolInputParser::parseNumberList(raw, 3);
    if (r.status == ToolInputParser::ParseStatus::Ok) {
        out = { r.values[0], r.values[1], r.values[2] };
        return true;
    }
    r = ToolInputParser::parseNumberList(raw, 6);
    if (r.status == ToolInputParser::ParseStatus::Ok) {
        out = { r.values[3], r.values[4], r.values[5] };
        return true;
    }
    return false;
}

QLineEdit* makeTextInput(QWidget* parent)
{
    auto* edit = new QLineEdit(parent);
    edit->setStyleSheet(Theme::inputStyle());
    return edit;
}

// ArrowComboBox (the down-arrow repaint the global QSS needs) now lives in
// ui/ArrowComboBox.h: the measurement pages use the same widget.

// 用户反馈：内容多的窗口会长过屏幕，底部的按钮因此被任务栏挡住、点不到。
// 每个工具页现在各自套一层滚动区——面板缩小时是页面内部滚动，而不是把对话框
// 撑到屏幕外。 返回的是滚动区（它才是 stack 里的那一页），页面本身成为其内容。
QScrollArea* wrapScrollable(QWidget* page, QStackedWidget* stack)
{
    auto* scroll = new QScrollArea(stack);
    scroll->setFrameShape(QFrame::NoFrame);
    scroll->setWidgetResizable(true);
    scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    scroll->setVerticalScrollBarPolicy(Qt::ScrollBarAsNeeded);
    scroll->setStyleSheet(QStringLiteral("QScrollArea { background: transparent; }"));
    scroll->setWidget(page);   // reparents the page into the scroll viewport
    return scroll;
}

QString parseErrorText(const ToolInputParser::ParseResult& r, std::size_t expected)
{
    switch (r.status) {
    case ToolInputParser::ParseStatus::Ok:
        return {};
    case ToolInputParser::ParseStatus::NonAscii:
        return QStringLiteral("包含中文/全角字符，请使用英文逗号和空格分隔");
    case ToolInputParser::ParseStatus::WrongCount:
        return QStringLiteral("需要 %1 个数值，当前 %2 个")
            .arg(static_cast<qulonglong>(expected))
            .arg(static_cast<qulonglong>(r.tokenCount));
    case ToolInputParser::ParseStatus::InvalidToken:
        return QStringLiteral("存在无法解析的数值：%1")
            .arg(QString::fromStdString(r.badToken));
    }
    return {};
}

} // namespace

ToolsPanel::ToolsPanel(QWidget* parent)
    : QDialog(parent)
{
    setWindowTitle(QStringLiteral("工具"));
    // 与主窗口一样可自由缩放/最大化；内容超出时由各页自己的滚动区消化，
    // 所以最小值只保证左列表 + 一页基本信息还看得见。
    setMinimumSize(640, 440);
    resize(820, 620);
    setWindowFlags(windowFlags() | Qt::WindowMinMaxButtonsHint);
    setAttribute(Qt::WA_DeleteOnClose, false);
    buildUi();
}

void ToolsPanel::buildUi()
{
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(16, 16, 16, 16);
    layout->setSpacing(16);

    m_toolList = new QListWidget(this);
    // Codex 的 UIA 驱动靠 objectName 找控件；测量方法页（P3）也是从这一个
    // 列表里选中的，所以给它一个稳定的名字。列表项的文本 = 方法名。
    m_toolList->setObjectName(QStringLiteral("tool_list"));
    m_toolList->setFixedWidth(140);
    m_toolList->addItem(QStringLiteral("欧氏距离"));
    m_toolList->addItem(QStringLiteral("像素→3D"));
    m_toolList->addItem(QStringLiteral("手眼标定"));
    m_toolList->addItem(QStringLiteral("坐标转换"));
    m_toolList->addItem(QStringLiteral("机器人数据格式推算"));
    m_toolList->addItem(QStringLiteral("机器人通信"));
    // 测量方法不再是一个"测量页 + 方法下拉框"，而是下面 buildMeasurePages()
    // 加进来的 8 个独立列表项（P3）。
    m_toolList->setStyleSheet(QStringLiteral(
        "QListWidget { background: %1; border: 1px solid %2; border-radius: %3px;"
        " font-size: %4px; }"
        "QListWidget::item { padding: 8px 10px; }"
        "QListWidget::item:selected { background: %6; color: %5; }")
        .arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS)
        .arg(Theme::FONT_BODY).arg(Theme::PRIMARY)
        .arg(Theme::withAlpha(Theme::PRIMARY, 0.12)));
    layout->addWidget(m_toolList);

    m_stack = new QStackedWidget(this);
    buildDistancePage(m_stack);
    buildPixelTo3DPage(m_stack);
    buildCalibrationPage(m_stack);
    buildTransformPage(m_stack);
    buildFormatInferencePage(m_stack);
    buildRobotCommPage(m_stack);
    buildMeasurePages(m_stack);
    layout->addWidget(m_stack, 1);

    connect(m_toolList, &QListWidget::currentRowChanged,
            m_stack, &QStackedWidget::setCurrentIndex);
    // 换项时除了换页，还要把当前 ROI 推给新的方法页、并按 P4 写一条 [测量-说明]。
    connect(m_toolList, &QListWidget::currentRowChanged,
            this, &ToolsPanel::onToolChanged);
    m_toolList->setCurrentRow(0);

    m_calibWatcher = new QFutureWatcher<CalibrationService::Result>(this);
    connect(m_calibWatcher,
            &QFutureWatcher<CalibrationService::Result>::finished,
            this, &ToolsPanel::onCalibrationFinished);
    m_calibTryAllWatcher = new QFutureWatcher<QString>(this);
    connect(m_calibTryAllWatcher, &QFutureWatcher<QString>::finished,
            this, &ToolsPanel::onTryAllFinished);
}

void ToolsPanel::setAppConfig(AppConfig* cfg)
{
    m_config = cfg;
    // 预设读进来之后把下拉框摆到预设那一项上，并显示"已应用"。
    if (m_config && m_calibFormatCombo) {
        const auto fmt = m_config->calibPoseFormat();
        // 预设可能落在常用档（绝大多数）或高级档；两档都展开后再定位。
        rebuildFormatCombo(m_calibFormatCombo,
                           RobotDataFormats::tier(fmt) == RobotDataFormats::Tier::Advanced,
                           true, fmt);
        if (m_calibAdvancedCheck)
            m_calibAdvancedCheck->setChecked(
                RobotDataFormats::tier(fmt) == RobotDataFormats::Tier::Advanced);
        m_calibAngleUnitCombo->setCurrentIndex(
            m_config->calibPoseAngleUnit() == TransformTools::AngleUnit::Radian ? 1 : 0);
        updateCalibFormatHint();
    }
}

RobotDataFormats::Id ToolsPanel::currentCalibPoseFormat() const
{
    return comboFormat(m_calibFormatCombo, RobotDataFormats::Id::EulerSxyz);
}

TransformTools::AngleUnit ToolsPanel::currentCalibAngleUnit() const
{
    return (m_calibAngleUnitCombo && m_calibAngleUnitCombo->currentIndex() == 1)
        ? TransformTools::AngleUnit::Radian : TransformTools::AngleUnit::Degree;
}

void ToolsPanel::updateCalibFormatHint()
{
    if (!m_calibFormatLabel)
        return;

    const auto fmt = currentCalibPoseFormat();
    const auto unit = currentCalibAngleUnit();
    QString state;
    if (!m_config) {
        state = QStringLiteral("（未接上配置，本次设置不会保存）");
    } else if (fmt == m_config->calibPoseFormat()
               && unit == m_config->calibPoseAngleUnit()) {
        state = QStringLiteral("已应用为全局预设：主界面「计算」也按此格式，重启后仍生效");
    } else {
        // 改了下拉框但没点「应用」：说清楚谁会跟着变、谁不会。
        state = QStringLiteral("未应用 —— 主界面「计算」仍按「%1 · %2」；本页「计算」按上面选的")
                    .arg(CalibrationService::poseFormatName(m_config->calibPoseFormat()),
                         m_config->calibPoseAngleUnit() == TransformTools::AngleUnit::Radian
                             ? QStringLiteral("弧度") : QStringLiteral("度"));
    }
    // 本页下拉框选的是「卡片那 3 个旋转数怎么读」，不是 SDK 的 poseType。
    // 写清楚交给 SDK 的到底是哪一种，避免和官方 UI 的 4 项列表对不上号。
    const int sdkType = CalibrationService::sdkPoseType(fmt);
    QString sdkNote;
    if (sdkType == 0) {
        sdkNote = QStringLiteral(
            "交给 HandEyeSDK：欧拉角（poseType=0）—— 原样透传，SDK 自己按 sXYZ 读");
    } else if (sdkType == 3) {
        sdkNote = QStringLiteral(
            "交给 HandEyeSDK：4×4 姿态变换矩阵（poseType=3）—— "
            "本工具已把该欧拉约定转成矩阵");
    } else {
        sdkNote = QStringLiteral(
            "该格式需要更多旋转值，卡片装不下，标定不会把它交给 HandEyeSDK");
    }
    // 卡片固定 6 个数（位置 + 3 个旋转值）是红线，所以本页下拉框只列 3 旋转数的
    // 欧拉类约定；四元数（4 个数）与 4×4 姿态变换矩阵（16 个数）放在「坐标转换」
    // 页。两个页面的选项不同是有意的，这里写明原因，免得看着像功能缺失。
    const QString cardNote = QStringLiteral(
        "卡片固定 6 个数，所以本页只列 3 个旋转数的约定；"
        "四元数与 4×4 姿态变换矩阵请到「坐标转换」页使用。");
    m_calibFormatLabel->setText(CalibrationService::poseFormatDescription(fmt)
                                + QStringLiteral("\n") + sdkNote
                                + QStringLiteral("\n") + state
                                + QStringLiteral("\n") + cardNote);
}

void ToolsPanel::applyCalibPoseFormat()
{
    if (!m_config)
        return;
    m_config->setCalibPoseFormat(currentCalibPoseFormat(), currentCalibAngleUnit());
    updateCalibFormatHint();
    m_calibHint->clear();
    emit logMessage(QStringLiteral("[标定] 位姿格式预设已应用：%1 · %2")
                        .arg(CalibrationService::poseFormatName(currentCalibPoseFormat()),
                             currentCalibAngleUnit() == TransformTools::AngleUnit::Radian
                                 ? QStringLiteral("弧度") : QStringLiteral("度")));
}

void ToolsPanel::buildDistancePage(QStackedWidget* stack)
{
    auto* page = new QWidget(stack);
    auto* pageLayout = new QVBoxLayout(page);

    auto* group = new QGroupBox(QStringLiteral("欧氏距离"), page);
    auto* form = new QFormLayout(group);

    m_p1Input = makeTextInput(group);
    m_p1Input->setObjectName(QStringLiteral("point1_input"));
    m_p1Input->setPlaceholderText(QStringLiteral(
        "x, y, z，英文逗号/空格分隔，可直接复制粘贴"));
    form->addRow(QStringLiteral("点 1 (x y z)"), m_p1Input);

    m_p2Input = makeTextInput(group);
    m_p2Input->setObjectName(QStringLiteral("point2_input"));
    m_p2Input->setPlaceholderText(QStringLiteral(
        "x, y, z，英文逗号/空格分隔，可直接复制粘贴"));
    form->addRow(QStringLiteral("点 2 (x y z)"), m_p2Input);

    m_unitCombo = new QComboBox(group);
    m_unitCombo->addItem(QStringLiteral("毫米 (mm)"));
    m_unitCombo->addItem(QStringLiteral("厘米 (cm)"));
    m_unitCombo->addItem(QStringLiteral("米 (m)"));
    m_unitCombo->setStyleSheet(Theme::comboBoxStyle());
    form->addRow(QStringLiteral("显示单位"), m_unitCombo);

    auto* resultRow = new QHBoxLayout();
    m_resultLabel = new QLabel(QStringLiteral("距离 = --"), group);
    m_resultLabel->setObjectName(QStringLiteral("distance_result"));
    m_resultLabel->setStyleSheet(QStringLiteral(
        "font-size: %1px; font-weight: 600; color: %2;")
        .arg(Theme::FONT_H2).arg(Theme::PRIMARY));
    resultRow->addWidget(m_resultLabel);
    resultRow->addStretch();
    m_calcBtn = new QPushButton(QStringLiteral("计算"), group);
    m_calcBtn->setStyleSheet(Theme::primaryButtonStyle());
    resultRow->addWidget(m_calcBtn);
    m_copyBtn = new QPushButton(QStringLiteral("复制"), group);
    m_copyBtn->setStyleSheet(Theme::secondaryButtonStyle());
    resultRow->addWidget(m_copyBtn);
    form->addRow(QStringLiteral("结果"), resultRow);

    m_distanceHint = new QLabel(group);
    m_distanceHint->setObjectName(QStringLiteral("distance_hint"));
    m_distanceHint->setStyleSheet(QStringLiteral(
        "color: %1; font-size: %2px;").arg(Theme::ERROR).arg(Theme::FONT_HINT));
    m_distanceHint->setWordWrap(true);
    form->addRow(QString(), m_distanceHint);

    pageLayout->addWidget(group);
    pageLayout->addStretch();
    stack->addWidget(wrapScrollable(page, stack));

    // Manual calculation: result updates only when 计算 is clicked.
    connect(m_calcBtn, &QPushButton::clicked, this, &ToolsPanel::updateDistanceResult);
    connect(m_copyBtn, &QPushButton::clicked, this, [this]() {
        if (!m_resultLabel->text().isEmpty())
            QApplication::clipboard()->setText(m_resultLabel->text());
    });
    for (QLineEdit* edit : { m_p1Input, m_p2Input })
        connect(edit, &QLineEdit::textChanged, this, [this](const QString&) {
            m_distanceHint->clear();
        });
}

void ToolsPanel::updateDistanceResult()
{
    ToolInputParser::ParseResult p1 = ToolInputParser::parseNumberList(
        m_p1Input->text().toStdString(), 3);
    if (p1.status != ToolInputParser::ParseStatus::Ok) {
        m_distanceHint->setText(
            QStringLiteral("点 1：%1").arg(parseErrorText(p1, 3)));
        return;
    }
    ToolInputParser::ParseResult p2 = ToolInputParser::parseNumberList(
        m_p2Input->text().toStdString(), 3);
    if (p2.status != ToolInputParser::ParseStatus::Ok) {
        m_distanceHint->setText(
            QStringLiteral("点 2：%1").arg(parseErrorText(p2, 3)));
        return;
    }
    m_distanceHint->clear();
    const double d = GeometryTools::distance3d(
        p1.values[0], p1.values[1], p1.values[2],
        p2.values[0], p2.values[1], p2.values[2]);
    const auto unit = static_cast<GeometryTools::LengthUnit>(m_unitCombo->currentIndex());
    m_resultLabel->setText(
        QStringLiteral("距离 = %1").arg(GeometryTools::formatDistance(d, unit)));
}

void ToolsPanel::buildPixelTo3DPage(QStackedWidget* stack)
{
    auto* page = new QWidget(stack);
    auto* pageLayout = new QVBoxLayout(page);

    auto* group = new QGroupBox(QStringLiteral("像素→3D（离线反投影）"), page);
    auto* form = new QFormLayout(group);
    form->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);

    // Online / offline switch.  Offline (default) reads a local png + ply and
    // picks the pixel on the main 2D view; online (camera) is not wired yet.
    m_p2dModeCombo = new ArrowComboBox(group);
    m_p2dModeCombo->setObjectName(QStringLiteral("p2d_mode"));
    m_p2dModeCombo->setStyleSheet(Theme::comboBoxStyle());
    m_p2dModeCombo->addItem(QStringLiteral("离线（加载本地文件，用主 2D 视窗取点）"));
    m_p2dModeCombo->addItem(QStringLiteral("在线（相机实时）"));
    m_p2dModeCombo->setCurrentIndex(0);
    form->addRow(QStringLiteral("模式"), m_p2dModeCombo);

    // Data folder
    auto* dirWrap = new QWidget(group);
    auto* dirRow = new QHBoxLayout(dirWrap);
    dirRow->setContentsMargins(0, 0, 0, 0);
    dirRow->setSpacing(8);
    m_p2dDir = makeTextInput(dirWrap);
    m_p2dDir->setObjectName(QStringLiteral("p2d_dir"));
    m_p2dDir->setPlaceholderText(QStringLiteral("选择含 png + ply 的会话文件夹"));
    dirRow->addWidget(m_p2dDir, 1);
    auto* browseBtn = new QPushButton(QStringLiteral("浏览"), dirWrap);
    browseBtn->setStyleSheet(Theme::secondaryButtonStyle());
    dirRow->addWidget(browseBtn);
    form->addRow(QStringLiteral("数据文件夹"), dirWrap);

    // Image file
    m_p2dImageCombo = new ArrowComboBox(group);
    m_p2dImageCombo->setObjectName(QStringLiteral("p2d_image"));
    m_p2dImageCombo->setStyleSheet(Theme::comboBoxStyle());
    form->addRow(QStringLiteral("2D 图像"), m_p2dImageCombo);

    // Camera intrinsics / extrinsics (optional; needed when the point cloud
    // is not pixel-aligned, e.g. SwingLineScan + correspond2d=false)
    m_p2dIntrinsic = makeTextInput(group);
    m_p2dIntrinsic->setObjectName(QStringLiteral("p2d_intrinsic"));
    m_p2dIntrinsic->setPlaceholderText(QStringLiteral(
        "fx 0 cx; 0 fy cy; 0 0 1（行主序 9 值，可选；未对齐时必填）"));
    form->addRow(QStringLiteral("相机内参"), m_p2dIntrinsic);

    m_p2dExtrinsic = makeTextInput(group);
    m_p2dExtrinsic->setObjectName(QStringLiteral("p2d_extrinsic"));
    m_p2dExtrinsic->setPlaceholderText(QStringLiteral(
        "4×4 行主序 16 值，可选，默认单位阵（点云→图像坐标系变换）"));
    form->addRow(QStringLiteral("相机外参"), m_p2dExtrinsic);

    // Pixel input
    m_p2dPixel = makeTextInput(group);
    m_p2dPixel->setObjectName(QStringLiteral("p2d_pixel"));
    m_p2dPixel->setPlaceholderText(QStringLiteral(
        "x, y（像素坐标，也可在主 2D 视窗上左键点击取点）"));
    form->addRow(QStringLiteral("像素坐标"), m_p2dPixel);

    // 在线模式下整组禁用的文件输入（连同它们的标签）。
    const QVector<QWidget*> offlineFields = {
        dirWrap, m_p2dImageCombo, m_p2dIntrinsic, m_p2dExtrinsic
    };
    m_p2dOfflineOnly = offlineFields;
    for (QWidget* field : offlineFields) {
        if (QWidget* label = form->labelForField(field))
            m_p2dOfflineOnly.append(label);
    }

    // Result + actions
    auto* resultRow = new QHBoxLayout();
    resultRow->setSpacing(8);
    auto* resultCaption = new QLabel(QStringLiteral("结果"), group);
    resultCaption->setStyleSheet(QStringLiteral(
        "font-size: %1px; color: %2;")
        .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    resultRow->addWidget(resultCaption);
    m_p2dResult = new QLabel(QStringLiteral("--"), group);
    m_p2dResult->setObjectName(QStringLiteral("p2d_result"));
    m_p2dResult->setStyleSheet(QStringLiteral(
        "font-size: %1px; font-weight: 600; color: %2;")
        .arg(Theme::FONT_H2).arg(Theme::PRIMARY));
    resultRow->addWidget(m_p2dResult, 1);
    auto* calcBtn = new QPushButton(QStringLiteral("计算"), group);
    calcBtn->setStyleSheet(Theme::primaryButtonStyle());
    resultRow->addWidget(calcBtn);
    m_p2dCopyBtn = new QPushButton(QStringLiteral("复制"), group);
    m_p2dCopyBtn->setStyleSheet(Theme::secondaryButtonStyle());
    resultRow->addWidget(m_p2dCopyBtn);
    form->addRow(resultRow);

    m_p2dHint = new QLabel(group);
    m_p2dHint->setObjectName(QStringLiteral("p2d_hint"));
    m_p2dHint->setStyleSheet(QStringLiteral(
        "color: %1; font-size: %2px;").arg(Theme::ERROR).arg(Theme::FONT_HINT));
    m_p2dHint->setWordWrap(true);
    form->addRow(QString(), m_p2dHint);

    pageLayout->addWidget(group);
    pageLayout->addStretch();

    // 这一页**只能**被包一次滚动区：wrapScrollable() 会把 page 重新挂到滚动区的
    // 视口里，套第二次就会把 page 从第一个滚动区手里抢走——第一个滚动区变成既
    // 不在任何 layout 里、又还挂在 stack 上的孤儿，停在 stack 左上角（选中「欧氏
    // 距离」时正好压住那一页的标题），而且选中本页会以 0xC00000FD 崩掉。
    // 冻结判据「当前页是不是像素→3D」比对的是 stack 里的那一页，所以存下来的必须
    // 就是塞进 stack 的那一个滚动区（见 §8 契约冻结）。
    m_p2dPage = wrapScrollable(page, stack);
    stack->addWidget(m_p2dPage);

    connect(browseBtn, &QPushButton::clicked, this, [this]() {
        const QString dir = QFileDialog::getExistingDirectory(
            this, QStringLiteral("选择数据文件夹"), m_p2dDir->text().trimmed());
        if (dir.isEmpty())
            return;
        m_p2dDir->setText(dir);
        refreshPixelTo3DImages();
    });
    connect(m_p2dModeCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int) { applyPixelTo3DMode(); });
    connect(m_p2dImageCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int index) { showPixelTo3DImage(index); });
    connect(calcBtn, &QPushButton::clicked, this, [this]() {
        // 在线模式的「计算」也走主窗口的同一套查询链路，不在这里另算一份。
        if (m_p2dOnline) {
            requestOnlinePixelQuery();
            return;
        }
        updatePixelTo3DResult();
    });
    connect(m_p2dCopyBtn, &QPushButton::clicked, this, [this]() {
        if (!m_p2dResultValue.isEmpty())
            QApplication::clipboard()->setText(m_p2dResultValue);
    });
    // 数据文件夹边打字边刷新图像列表（不只在点「浏览」时刷新）。
    connect(m_p2dDir, &QLineEdit::textChanged,
            this, [this](const QString&) { refreshPixelTo3DImages(); });
    for (QLineEdit* edit : { m_p2dIntrinsic, m_p2dExtrinsic, m_p2dPixel })
        connect(edit, &QLineEdit::textChanged, this, [this](const QString&) {
            m_p2dHint->clear();
        });
}

// 在线/离线开关落到控件上：在线禁用整组文件输入并给提示，离线恢复。
void ToolsPanel::applyPixelTo3DMode()
{
    const bool online = (m_p2dModeCombo->currentIndex() == 1);
    m_p2dOnline = online;
    for (QWidget* widget : m_p2dOfflineOnly)
        widget->setEnabled(!online);

    if (online) {
        m_p2dHint->setText(QStringLiteral(
            "在线：连接相机并拍照后，在主 2D 视窗左键取点"));
        updateOfflineFreeze();
        return;
    }

    m_p2dHint->clear();
    // 离线：若条件齐备就把主 2D 视窗切到当前选中的 png（否则保持解冻）。
    updateOfflineFreeze();
}

// 冻结的唯一判据：面板可见 + 当前工具页是「像素→3D」+ 离线模式且图像有效。
// 任一不满足 → 立刻解冻。所有状态转换（开/关面板、换工具页、切模式、改目录）
// 都汇到这里，避免出现"打开面板就冻结"这类错配。
void ToolsPanel::updateOfflineFreeze(bool requireVisible)
{
    const bool onPixelTo3DPage =
        (m_stack != nullptr && m_p2dPage != nullptr
         && m_stack->currentWidget() == m_p2dPage);
    const QString dir = m_p2dDir ? m_p2dDir->text().trimmed() : QString();
    const int index = m_p2dImageCombo ? m_p2dImageCombo->currentIndex() : -1;
    const bool hasImage = !dir.isEmpty() && index >= 0
        && index < m_p2dImageCombo->count();

    if ((requireVisible && !isVisible()) || !onPixelTo3DPage || m_p2dOnline
        || !hasImage) {
        emit pixelTo3DOfflineImageEnded();
        return;
    }
    emit pixelTo3DOfflineImageRequested(
        dir + QLatin1Char('/') + m_p2dImageCombo->itemText(index));
}

void ToolsPanel::refreshPixelTo3DImages()
{
    const QString dir = m_p2dDir->text().trimmed();
    m_p2dImageCombo->clear();
    if (!dir.isEmpty()) {
        QDir qdir(dir);
        const QStringList pngs = qdir.entryList(
            { QStringLiteral("*.png"), QStringLiteral("*.jpg"), QStringLiteral("*.bmp") },
            QDir::Files, QDir::Name);
        for (const QString& name : pngs)
            m_p2dImageCombo->addItem(name);
    }
    if (!dir.isEmpty() && m_p2dImageCombo->count() == 0)
        m_p2dHint->setText(QStringLiteral("该目录下没有 png 图像"));
    // 目录/显式选择变了 → 按同一套判据重算冻结（空目录自动解冻）。
    updateOfflineFreeze();
}

// 离线取点：把当前 png 交给主窗口冻结到主 2D 视窗上（是否真的冻结由
// updateOfflineFreeze() 的三条判据决定，这里不再自己判断）。
void ToolsPanel::showPixelTo3DImage(int index)
{
    Q_UNUSED(index);
    updateOfflineFreeze();
}

void ToolsPanel::onMainViewPixelClicked(int x, int y)
{
    if (m_p2dOnline || !isVisible())
        return;
    m_p2dPixel->setText(QStringLiteral("%1, %2").arg(x).arg(y));
    m_p2dHint->clear();
    updatePixelTo3DResult();
}

// 在线模式点「计算」：手输像素 → 请主窗口用当前采集帧查询。
void ToolsPanel::requestOnlinePixelQuery()
{
    const ToolInputParser::ParseResult pixel = ToolInputParser::parseNumberList(
        m_p2dPixel->text().toStdString(), 2);
    if (pixel.status != ToolInputParser::ParseStatus::Ok) {
        m_p2dHint->setText(
            QStringLiteral("像素坐标：%1").arg(parseErrorText(pixel, 2)));
        return;
    }
    emit pixelTo3DOnlineQueryRequested(
        static_cast<int>(pixel.values[0]), static_cast<int>(pixel.values[1]));
}

// 主窗口回填：在线取点的结果行 + hint。
void ToolsPanel::setOnlinePixelResult(int pixelX, int pixelY, bool ok,
                                      double xMm, double yMm, double zMm,
                                      const QString& message)
{
    if (!ok) {
        m_p2dResultValue.clear();
        m_p2dResult->setText(QStringLiteral("--"));
        m_p2dHint->setText(message.isEmpty()
            ? QStringLiteral("该像素无有效 3D 点（背景或无效深度）")
            : message);
        return;
    }
    const std::array<double, 3> point{ xMm, yMm, zMm };
    m_p2dResultValue =
        QString::fromStdString(PixelTo3DService::formatPoint(point));
    m_p2dResult->setText(m_p2dResultValue);
    m_p2dHint->setText(
        QStringLiteral("像素 (%1, %2) → 3D").arg(pixelX).arg(pixelY));
}

void ToolsPanel::showEvent(QShowEvent* event)
{
    QDialog::showEvent(event);
    // showEvent 期间 isVisible() 未必已经为 true，这里显式按「正在显示」评估：
    // 仍然要求当前页是「像素→3D」且离线+图像有效，才冻结主 2D 视窗。
    updateOfflineFreeze(false);
}

void ToolsPanel::hideEvent(QHideEvent* event)
{
    // 关闭（或最小化）工具页：把主 2D 视窗还给实时/采集图。
    emit pixelTo3DOfflineImageEnded();
    QDialog::hideEvent(event);
}

void ToolsPanel::updatePixelTo3DResult()
{
    m_p2dHint->clear();
    auto fail = [this](const QString& message) {
        m_p2dHint->setText(message);
    };

    const QString dir = m_p2dDir->text().trimmed();
    if (dir.isEmpty() || m_p2dImageCombo->count() == 0) {
        fail(QStringLiteral("请先选择包含 png/ply 的数据文件夹"));
        return;
    }
    const QString pngPath = dir + QLatin1Char('/') + m_p2dImageCombo->currentText();
    QFileInfo pngInfo(pngPath);
    const QString plyPath = dir + QLatin1Char('/') + pngInfo.completeBaseName()
        + QStringLiteral(".ply");
    if (!QFileInfo::exists(plyPath)) {
        fail(QStringLiteral("未找到与图像同名的点云文件: %1")
                 .arg(QFileInfo(plyPath).fileName()));
        return;
    }

    ToolInputParser::ParseResult pixel = ToolInputParser::parseNumberList(
        m_p2dPixel->text().toStdString(), 2);
    if (pixel.status != ToolInputParser::ParseStatus::Ok) {
        fail(QStringLiteral("像素坐标：%1").arg(parseErrorText(pixel, 2)));
        return;
    }

    QImage img(pngPath);
    if (img.isNull()) {
        fail(QStringLiteral("图像加载失败: %1").arg(pngInfo.fileName()));
        return;
    }
    const int w = img.width();
    const int h = img.height();
    const int px = static_cast<int>(pixel.values[0]);
    const int py = static_cast<int>(pixel.values[1]);

    const auto ply = PlyPointReader::read(plyPath.toStdString());
    if (!ply.ok) {
        fail(QStringLiteral("点云读取失败: %1")
                 .arg(QString::fromStdString(ply.error)));
        return;
    }

    // Intrinsics/extrinsics are only needed by the non-aligned path; a parse
    // failure is reported below only when the shared service asks for them.
    const ToolInputParser::ParseResult ik = ToolInputParser::parseNumberList(
        m_p2dIntrinsic->text().toStdString(), 9);
    const bool hasIntrinsics = (ik.status == ToolInputParser::ParseStatus::Ok);

    std::array<double, 16> ext{};
    const ToolInputParser::ParseResult ek = ToolInputParser::parseNumberList(
        m_p2dExtrinsic->text().toStdString(), 16);
    const bool extGiven = !m_p2dExtrinsic->text().trimmed().isEmpty();
    const bool hasExtrinsics =
        extGiven && ek.status == ToolInputParser::ParseStatus::Ok;
    // 非空但解析失败的外参不静默忽略。
    if (extGiven && !hasExtrinsics) {
        fail(QStringLiteral("相机外参：%1").arg(parseErrorText(ek, 16)));
        return;
    }
    if (hasExtrinsics) {
        for (int i = 0; i < 16; ++i)
            ext[static_cast<std::size_t>(i)] = ek.values[i];
    }

    PixelTo3DService::Source src;
    src.xyzMm = &ply.xyz;
    src.imageWidth = w;
    src.imageHeight = h;
    src.hasIntrinsics = hasIntrinsics;
    if (hasIntrinsics) {
        src.intrinsics.fx = ik.values[0];
        src.intrinsics.fy = ik.values[4];
        src.intrinsics.cx = ik.values[2];
        src.intrinsics.cy = ik.values[5];
    }
    src.extrinsics16 = hasExtrinsics ? ext.data() : nullptr;

    const PixelTo3DService::Query q = PixelTo3DService::query(src, px, py);
    if (q.status == PixelTo3DService::Status::Ok) {
        m_p2dResultValue = QString::fromStdString(
            PixelTo3DService::formatPoint(q.pointMm));
        m_p2dResult->setText(m_p2dResultValue);
        return;
    }

    if (q.status == PixelTo3DService::Status::MissingIntrinsics
        && ik.status != ToolInputParser::ParseStatus::Ok) {
        fail(QStringLiteral("点云与图像尺寸不一致，需要相机内参：%1")
                 .arg(parseErrorText(ik, 9)));
        return;
    }
    fail(QString::fromStdString(PixelTo3DService::statusText(q.status)));
}

void ToolsPanel::chooseCalibrationFile(QLineEdit* edit, const QString& title)
{
    if (!edit)
        return;

    // 起始位置：优先当前数据文件夹，其次输入框里那个文件所在的目录。
    const QString raw = edit->text().trimmed();
    const QString dirText = m_calibDir ? m_calibDir->text().trimmed() : QString();
    QString startDir = dirText;
    QString startFile;
    if (!raw.isEmpty()) {
        const QString abs = QFileInfo(raw).isAbsolute()
            ? raw : QDir(dirText).filePath(raw);
        const QFileInfo fi(abs);
        if (fi.absoluteDir().exists()) {
            startDir = fi.absolutePath();
            startFile = fi.fileName();
        }
    }
    if (startDir.isEmpty() || !QDir(startDir).exists())
        startDir = QDir::homePath();

    const QString chosen = QFileDialog::getOpenFileName(
        this, title, QDir(startDir).filePath(startFile),
        QStringLiteral("文本文件 (*.txt);;所有文件 (*.*)"));
    if (chosen.isEmpty())
        return;

    const QFileInfo fi(chosen);
    // 文件就在当前数据文件夹里 → 只写文件名（会话目录是相对的）；
    // 选了别的目录 → 连数据文件夹一起改，否则「计算」还是去老目录找。
    if (m_calibDir && !dirText.isEmpty()
        && QDir(dirText).absolutePath() == fi.absolutePath()) {
        edit->setText(fi.fileName());
        return;
    }
    if (m_calibDir)
        m_calibDir->setText(fi.absolutePath());
    edit->setText(fi.fileName());
}

void ToolsPanel::buildCalibrationPage(QStackedWidget* stack)
{
    auto* page = new QWidget(stack);
    auto* pageLayout = new QVBoxLayout(page);

    auto* group = new QGroupBox(QStringLiteral("手眼标定（离线计算）"), page);
    auto* form = new QFormLayout(group);
    form->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
    m_calibForm = form;

    // Data folder
    auto* dirRow = new QHBoxLayout();
    dirRow->setSpacing(8);
    m_calibDir = makeTextInput(group);
    m_calibDir->setObjectName(QStringLiteral("calib_dir"));
    m_calibDir->setPlaceholderText(QStringLiteral(
        "选择会话文件夹（1.png/1.ply ... + 位姿文件）"));
    dirRow->addWidget(m_calibDir, 1);
    auto* browseBtn = new QPushButton(QStringLiteral("浏览"), group);
    browseBtn->setStyleSheet(Theme::secondaryButtonStyle());
    dirRow->addWidget(browseBtn);
    form->addRow(QStringLiteral("数据文件夹"), dirRow);

    // 标定方式：既决定下面哪几行要填，也决定「计算」走哪个 SDK 接口。
    // 以前这里没有这一项，两个方法都走 HandEyeCalibrationMarker —— 戳点标定
    // 必然报「第 1 组机器人拍照位姿格式无效」。
    m_calibTypeCombo = new ArrowComboBox(group);
    m_calibTypeCombo->addItem(QStringLiteral("标定板识别（同心圆 / 黑白圆）"));
    m_calibTypeCombo->addItem(QStringLiteral("戳点标定（TCP touch）"));
    m_calibTypeCombo->setStyleSheet(Theme::comboBoxStyle());
    form->addRow(QStringLiteral("标定方式"), m_calibTypeCombo);

    // 文件行 = 输入框 + 「浏览」：以前只能手写文件名，现场没人记得住
    // cameraCapturePointXyz.txt 这种名字（用户 2026-10-19 反馈）。
    auto addFileRow = [this, form, group](const QString& label, const QString& objName,
                                          const QString& defName, QLineEdit*& edit,
                                          QWidget*& rowWidget, const QString& title) {
        edit = makeTextInput(group);
        edit->setObjectName(objName);
        edit->setText(defName);
        auto* row = new QHBoxLayout();
        row->setSpacing(8);
        row->addWidget(edit, 1);
        auto* browse = new QPushButton(QStringLiteral("浏览"), group);
        browse->setStyleSheet(Theme::secondaryButtonStyle());
        row->addWidget(browse);
        rowWidget = new QWidget(group);
        rowWidget->setLayout(row);
        form->addRow(label, rowWidget);
        connect(browse, &QPushButton::clicked, this,
                [this, edit, title]() { chooseCalibrationFile(edit, title); });
    };

    addFileRow(QStringLiteral("位姿文件"), QStringLiteral("calib_pose_file"),
               QStringLiteral("pose.txt"), m_calibPoseFile, m_calibPoseFileRow,
               QStringLiteral("选择机器人位姿文件"));

    // 标定板 / 戳点两个方法的数据列不同（见 HandEye.h）：
    //   标定板 = 数据文件夹里的 1.png/1.ply + pose.txt
    //   戳点   = cameraCapturePointXyz.txt + tcp.txt (+ cameraCaptureRobotPose.txt 仅眼在手上)
    addFileRow(QStringLiteral("相机点位文件"), QStringLiteral("calib_camera_file"),
               QStringLiteral("cameraCapturePointXyz.txt"), m_calibCameraFile,
               m_calibCameraFileRow, QStringLiteral("选择相机点位文件"));
    addFileRow(QStringLiteral("戳点文件"), QStringLiteral("calib_tcp_file"),
               QStringLiteral("tcp.txt"), m_calibTcpFile, m_calibTcpFileRow,
               QStringLiteral("选择戳点文件"));

    m_calibEyeCombo = new ArrowComboBox(group);
    m_calibEyeCombo->addItem(QStringLiteral("眼在手外（相机固定）"));
    m_calibEyeCombo->addItem(QStringLiteral("眼在手上（相机装在末端）"));
    m_calibEyeCombo->setStyleSheet(Theme::comboBoxStyle());
    form->addRow(QStringLiteral("安装方式"), m_calibEyeCombo);

    m_calibMarkerCombo = new ArrowComboBox(group);
    m_calibMarkerCombo->addItem(QStringLiteral("同心圆"));
    m_calibMarkerCombo->addItem(QStringLiteral("黑白圆（标定板）"));
    m_calibMarkerCombo->setStyleSheet(Theme::comboBoxStyle());
    form->addRow(QStringLiteral("标定板类型"), m_calibMarkerCombo);

    m_calibPoseUnitCombo = new ArrowComboBox(group);
    m_calibPoseUnitCombo->addItem(QStringLiteral("mm"));
    m_calibPoseUnitCombo->addItem(QStringLiteral("m"));
    m_calibPoseUnitCombo->setStyleSheet(Theme::comboBoxStyle());
    form->addRow(QStringLiteral("位姿位置单位"), m_calibPoseUnitCombo);

    m_calibAngleUnitCombo = new ArrowComboBox(group);
    m_calibAngleUnitCombo->addItem(QStringLiteral("度"));
    m_calibAngleUnitCombo->addItem(QStringLiteral("弧度"));
    m_calibAngleUnitCombo->setStyleSheet(Theme::comboBoxStyle());
    form->addRow(QStringLiteral("位姿角度单位"), m_calibAngleUnitCombo);

    // 位姿格式：卡片里那 3 个旋转数该怎么读。以前这里没有这一项，卡片的值被
    // 无条件当欧拉角处理 —— UR 的轴角位姿因此会"算成功但算错"（残差 ≈30）。
    auto* fmtRow = new QHBoxLayout();
    fmtRow->setSpacing(8);
    m_calibFormatCombo = new ArrowComboBox(group);
    m_calibFormatCombo->setObjectName(QStringLiteral("calib_pose_format"));
    // 卡片只有 3 个旋转数：这里只列 RobotDataFormats 里 cardUsable 的格式。
    rebuildFormatCombo(m_calibFormatCombo, false, true, Id::EulerSxyz);
    m_calibFormatCombo->setStyleSheet(Theme::comboBoxStyle());
    fmtRow->addWidget(m_calibFormatCombo, 1);
    m_calibApplyBtn = new QPushButton(QStringLiteral("应用"), group);
    m_calibApplyBtn->setObjectName(QStringLiteral("calib_apply_format"));
    m_calibApplyBtn->setStyleSheet(Theme::secondaryButtonStyle());
    m_calibApplyBtn->setToolTip(QStringLiteral(
        "把这个格式设为全局预设：主界面「计算」按它算，重启后仍生效"));
    fmtRow->addWidget(m_calibApplyBtn);
    // 包一层 QWidget：整行的按需显隐靠 labelForField(widget)，布局本身不认。
    m_calibFormatRow = new QWidget(group);
    m_calibFormatRow->setLayout(fmtRow);
    form->addRow(QStringLiteral("机器人数据格式"), m_calibFormatRow);

    // 首尾同轴的 12 种默认不显示；勾上才进下拉框（保持当前选中项）。
    m_calibAdvancedCheck = new QCheckBox(
        QStringLiteral("显示高级格式（首尾同轴，如 ZYZ / XYX）"), group);
    form->addRow(QString(), m_calibAdvancedCheck);

    m_calibFormatLabel = new QLabel(group);
    m_calibFormatLabel->setObjectName(QStringLiteral("calib_format_note"));
    m_calibFormatLabel->setStyleSheet(QStringLiteral(
        "color: %1; font-size: %2px;").arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));
    m_calibFormatLabel->setWordWrap(true);
    form->addRow(QString(), m_calibFormatLabel);

    m_calibAutoRemove = new QCheckBox(
        QStringLiteral("自动剔除大误差数据（SDK 内置）"), group);
    m_calibAutoRemove->setChecked(true);
    form->addRow(QString(), m_calibAutoRemove);

    m_calibResult = new QTextEdit(group);
    m_calibResult->setObjectName(QStringLiteral("calib_result"));
    m_calibResult->setReadOnly(true);
    m_calibResult->setMinimumHeight(180);
    m_calibResult->setStyleSheet(QStringLiteral(
        "background: %1; border: 1px solid %2; border-radius: 4px; "
        "font-size: %3px; color: %4; font-family: Consolas, monospace;")
        .arg(Theme::BG_CARD).arg(Theme::BORDER_DEFAULT)
        .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    form->addRow(QStringLiteral("结果"), m_calibResult);

    auto* btnRow = new QHBoxLayout();
    btnRow->setSpacing(8);
    btnRow->addStretch();
    // 「试算各格式」已迁到「机器人数据格式推算」页的方式 ③（用户 2026-10-19 要求），
    // 本页只保留计算与当前会话。
    // 用户反馈 9：在线（当前会话）路径已知，一键算并把用的路径显示出来。
    m_calibSessionBtn = new QPushButton(QStringLiteral("用当前会话"), group);
    m_calibSessionBtn->setObjectName(QStringLiteral("calib_session_btn"));
    m_calibSessionBtn->setStyleSheet(Theme::secondaryButtonStyle());
    btnRow->addWidget(m_calibSessionBtn);
    m_calibCalcBtn = new QPushButton(QStringLiteral("计算"), group);
    m_calibCalcBtn->setStyleSheet(Theme::primaryButtonStyle());
    btnRow->addWidget(m_calibCalcBtn);
    m_calibCopyBtn = new QPushButton(QStringLiteral("复制结果"), group);
    m_calibCopyBtn->setStyleSheet(Theme::secondaryButtonStyle());
    btnRow->addWidget(m_calibCopyBtn);
    form->addRow(QString(), btnRow);

    m_calibHint = new QLabel(group);
    m_calibHint->setObjectName(QStringLiteral("calib_hint"));
    m_calibHint->setStyleSheet(QStringLiteral(
        "color: %1; font-size: %2px;").arg(Theme::ERROR).arg(Theme::FONT_HINT));
    m_calibHint->setWordWrap(true);
    form->addRow(QString(), m_calibHint);

    pageLayout->addWidget(group);
    pageLayout->addStretch();
    stack->addWidget(wrapScrollable(page, stack));

    connect(browseBtn, &QPushButton::clicked, this, [this]() {
        const QString dir = QFileDialog::getExistingDirectory(
            this, QStringLiteral("选择数据文件夹"), m_calibDir->text().trimmed());
        if (!dir.isEmpty())
            m_calibDir->setText(dir);
    });
    connect(m_calibCalcBtn, &QPushButton::clicked,
            this, &ToolsPanel::updateCalibrationResult);
    connect(m_calibSessionBtn, &QPushButton::clicked, this, [this]() {
        if (m_calibWatcher->isRunning())
            return;
        emit calibrationSessionRequested();
    });
    connect(m_calibCopyBtn, &QPushButton::clicked, this, [this]() {
        if (!m_calibResult->toPlainText().isEmpty())
            QApplication::clipboard()->setText(m_calibResult->toPlainText());
    });
    connect(m_calibApplyBtn, &QPushButton::clicked,
            this, &ToolsPanel::applyCalibPoseFormat);
    connect(m_calibAdvancedCheck, &QCheckBox::toggled, this, [this](bool on) {
        const Id current = currentCalibPoseFormat();
        rebuildFormatCombo(m_calibFormatCombo, on, true, current);
        updateCalibFormatHint();
    });
    for (QComboBox* combo : { m_calibFormatCombo, m_calibAngleUnitCombo })
        connect(combo, QOverload<int>::of(&QComboBox::currentIndexChanged),
                this, [this](int) { updateCalibFormatHint(); });
    updateCalibFormatHint();
    for (QLineEdit* edit : { m_calibDir, m_calibPoseFile, m_calibCameraFile, m_calibTcpFile })
        connect(edit, &QLineEdit::textChanged, this, [this](const QString&) {
            m_calibHint->clear();
            // 用户自己改路径 = 回到手工方式：丢掉「用当前会话」带来的内存数据，
            // 之后的「计算」按文件夹 + 文件走。
            m_sessionActive = false;
            m_sessionFolder.clear();
            m_sessionPoses.clear();
            m_sessionCamera.clear();
            m_sessionTcp.clear();
        });

    // 标定方式 / 安装方式变了 → 该显示哪几行、位姿文件叫什么名字都要跟着变。
    for (QComboBox* combo : { m_calibTypeCombo, m_calibEyeCombo })
        connect(combo, QOverload<int>::of(&QComboBox::currentIndexChanged),
                this, [this](int) {
                    m_calibHint->clear();
                    updateCalibrationModeVisibility();
                });
    updateCalibrationModeVisibility();
}

void ToolsPanel::updateCalibrationModeVisibility()
{
    if (!m_calibForm || !m_calibTypeCombo || !m_calibEyeCombo)
        return;

    const bool tcp = m_calibTypeCombo->currentIndex() == 1;
    const bool eyeInHand = m_calibEyeCombo->currentIndex() == 1;
    // 眼在手外 + 戳点标定没有机器人拍照位姿这一列（与 DataInputArea 卡片同判据）。
    const bool needPose = !tcp || eyeInHand;

    auto rowVisible = [this](QWidget* field, bool on) {
        if (!field) return;
        if (QWidget* label = m_calibForm->labelForField(field))
            label->setVisible(on);
        field->setVisible(on);
    };

    // 隐藏整行（输入框 + 「浏览」按钮），而不是只藏输入框。
    rowVisible(m_calibPoseFileRow, needPose);
    rowVisible(m_calibCameraFileRow, tcp);
    rowVisible(m_calibTcpFileRow, tcp);
    rowVisible(m_calibMarkerCombo, !tcp);
    rowVisible(m_calibPoseUnitCombo, needPose);
    rowVisible(m_calibAngleUnitCombo, needPose);
    // 位姿格式那两行跟"有没有拍照位姿这一列"同命。
    rowVisible(m_calibFormatRow, needPose);
    rowVisible(m_calibAdvancedCheck, needPose);
    rowVisible(m_calibFormatLabel, needPose);

    // 位姿文件的默认名随方式变（会话导出用哪份文件就填哪份），用户自己改过的不动。
    const QString cur = m_calibPoseFile->text().trimmed();
    const QString defMarker = QStringLiteral("pose.txt");
    const QString defTcp = QStringLiteral("cameraCaptureRobotPose.txt");
    if (needPose && (cur.isEmpty() || cur == defMarker || cur == defTcp)) {
        const QString want = tcp ? defTcp : defMarker;
        if (cur != want)
            m_calibPoseFile->setText(want);
    }

    // 推算页有一份自己的输入组（方法 ③ 用），显隐规则与这里一致。
    updateInferenceInputVisibility();
}

CalibrationService::Params ToolsPanel::calibParams() const
{
    CalibrationService::Params params;
    params.calibType = m_calibTypeCombo->currentIndex() == 1
        ? CalibType::TcpTouch : CalibType::Marker;
    params.eyeInHand = m_calibEyeCombo->currentIndex() == 1;
    params.markerType = m_calibMarkerCombo->currentIndex() == 0 ? 1 : 0;
    params.isPoseMm = m_calibPoseUnitCombo->currentIndex() == 0;
    // 本页「计算」按眼前选的那一项算（所见即所算）；「应用」只决定全局预设，
    // 也就是主界面「计算」用什么。两者可以暂时不一致，提示行会写清楚。
    params.poseFormat = currentCalibPoseFormat();
    params.poseAngleUnit = currentCalibAngleUnit();
    params.autoRemoveLargeError = m_calibAutoRemove->isChecked();
    return params;
}

void ToolsPanel::runCalibration(const QString& folder,
                                const std::vector<QString>& cameraLines,
                                const std::vector<QString>& poseLines,
                                const std::vector<QString>& tcpLines)
{
    const CalibrationService::Params params = calibParams();
    m_calibCalcBtn->setEnabled(false);
    m_calibCalcBtn->setText(QStringLiteral("计算中..."));
    m_calibWatcher->setFuture(QtConcurrent::run(
        [folder, cameraLines, poseLines, tcpLines, params]() {
            return CalibrationService::calibrate(folder, cameraLines, poseLines,
                                                 tcpLines, params);
        }));
}

void ToolsPanel::useCurrentSession(const QString& folder,
                                   const QStringList& cameraLines,
                                   const QStringList& poseLines,
                                   const QStringList& tcpLines,
                                   bool eyeInHand, bool marker, bool concentric)
{
    if (m_calibWatcher->isRunning())
        return;

    // 推算页点「用当前会话」时，载入后直接跑试算；标定页点来时仍走普通计算。
    const bool forTryAll = m_sessionForTryAll;
    m_sessionForTryAll = false;

    // 先写路径/方式再置状态：setText / setCurrentIndex 都会触发信号，
    // 那几个槽会清掉会话状态。
    m_calibDir->setText(folder);
    m_calibTypeCombo->setCurrentIndex(marker ? 0 : 1);
    m_calibEyeCombo->setCurrentIndex(eyeInHand ? 1 : 0);
    m_calibMarkerCombo->setCurrentIndex(concentric ? 0 : 1);
    updateCalibrationModeVisibility();
    m_calibResult->clear();

    auto clearSession = [this]() {
        m_sessionActive = false;
        m_sessionFolder.clear();
        m_sessionPoses.clear();
        m_sessionCamera.clear();
        m_sessionTcp.clear();
        updateInferenceDataLabel();
    };
    // 返回第一个空行的组号（1 基），没有空行返回 0。
    auto firstEmpty = [](const QStringList& lines) {
        for (int i = 0; i < lines.size(); ++i)
            if (lines[i].trimmed().isEmpty())
                return i + 1;
        return 0;
    };
    // 从推算页发起时，标定页的提示行看不见 —— 同一条原因也要写到推算页。
    auto reportFailure = [this, forTryAll](const QString& message) {
        m_calibHint->setText(message);
        if (forTryAll && m_inferHint) {
            m_inferHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                           .arg(Theme::ERROR).arg(Theme::FONT_HINT));
            m_inferHint->setText(message);
        }
    };

    if (folder.trimmed().isEmpty()) {
        clearSession();
        reportFailure(QStringLiteral(
            "当前会话还没有保存目录（请先保存一组标定数据）"));
        return;
    }

    // 按当前方式校验**本方式需要的那几列**是否整列有值。列不对齐就直接说清楚，
    // 别把错位的数据喂给 SDK（那样只会得到"数据无效"这种看不出原因的返回码）。
    const bool tcp = !marker;
    if (tcp) {
        if (cameraLines.isEmpty() || cameraLines.size() != tcpLines.size()
                || firstEmpty(cameraLines) > 0 || firstEmpty(tcpLines) > 0) {
            clearSession();
            reportFailure(QStringLiteral(
                "戳点标定需要每组的相机目标点与机器人目标点（当前会话这两列有缺失）"));
            return;
        }
        if (eyeInHand && (poseLines.size() != cameraLines.size() || firstEmpty(poseLines) > 0)) {
            clearSession();
            reportFailure(QStringLiteral(
                "眼在手上戳点标定还需要每组的机器人拍照位姿（当前会话有缺失）"));
            return;
        }
    } else if (poseLines.isEmpty() || firstEmpty(poseLines) > 0) {
        clearSession();
        reportFailure(QStringLiteral(
            "当前会话还没有可用的机器人拍照位姿（请先拍照并填写机器人位姿）"));
        return;
    }

    auto copyIn = [](const QStringList& src) {
        std::vector<QString> out;
        out.reserve(static_cast<std::size_t>(src.size()));
        for (const QString& line : src)
            out.push_back(line);
        return out;
    };

    m_sessionActive = true;
    m_sessionFolder = folder;
    m_sessionCamera = copyIn(cameraLines);
    m_sessionPoses = copyIn(poseLines);
    m_sessionTcp = copyIn(tcpLines);
    m_calibHint->setText(QStringLiteral("当前会话：%1（%2 组数据）")
        .arg(folder).arg(cameraLines.size()));
    updateInferenceDataLabel();
    if (forTryAll)
        runTryAllPoseFormats();
    else
        runCalibration(m_sessionFolder, m_sessionCamera, m_sessionPoses, m_sessionTcp);
}

// 主窗口换了会话（启动建第一组，或用户点了「新建会话」）。
// 缓存的三列必须丢掉：留着的话，会话模式下点「计算」会拿**上一组**的位姿配上
// 这一组的目录算出结果 —— 数字是错的，而界面上完全看不出来。
void ToolsPanel::clearSessionData()
{
    m_sessionActive = false;
    m_sessionFolder.clear();
    m_sessionCamera.clear();
    m_sessionPoses.clear();
    m_sessionTcp.clear();
    m_calibHint->clear();
    m_calibResult->clear();
    updateInferenceDataLabel();   // 推算页「方式 ③」的数据来源行跟着清掉
}

// 凑齐一次标定要的三列数据：优先「当前会话」的内存三列，否则按路径从磁盘读。
// 失败时把中文原因写进 m_calibHint 并返回 false（调用方直接 return，不用再管提示）。
bool ToolsPanel::gatherCalibrationInput(QString& folder,
                                        std::vector<QString>& cameraLines,
                                        std::vector<QString>& poseLines,
                                        std::vector<QString>& tcpLines,
                                        QString* errorOut)
{
    if (m_sessionActive) {
        // 会话模式：用内存里的三列（不是磁盘上的文件 —— 那边可能已被清理）。
        folder = m_sessionFolder;
        cameraLines = m_sessionCamera;
        poseLines = m_sessionPoses;
        tcpLines = m_sessionTcp;
        return true;
    }

    m_calibHint->clear();
    auto fail = [this, errorOut](const QString& message) {
        m_calibHint->setText(message);
        if (errorOut)
            *errorOut = message;
    };

    const QString dir = m_calibDir->text().trimmed();
    if (dir.isEmpty()) {
        fail(QStringLiteral("请先选择数据文件夹"));
        return false;
    }

    const CalibrationService::Params params = calibParams();
    const bool tcp = (params.calibType == CalibType::TcpTouch);
    const bool needPose = !tcp || params.eyeInHand;

    auto readLines = [&](const QLineEdit* edit, const QString& what,
                         std::vector<QString>& out) -> bool {
        const QString name = edit->text().trimmed();
        if (name.isEmpty()) {
            fail(QStringLiteral("%1文件名不能为空").arg(what));
            return false;
        }
        QFile file(dir + QLatin1Char('/') + name);
        if (!file.open(QIODevice::ReadOnly | QIODevice::Text)) {
            fail(QStringLiteral("无法读取%1: %2").arg(what).arg(name));
            return false;
        }
        QTextStream ts(&file);
        ts.setCodec("UTF-8");
        while (!ts.atEnd()) {
            const QString line = ts.readLine().trimmed();
            if (!line.isEmpty())
                out.push_back(line);
        }
        if (out.empty()) {
            fail(QStringLiteral("%1为空").arg(what));
            return false;
        }
        return true;
    };

    if (tcp) {
        if (!readLines(m_calibCameraFile, QStringLiteral("相机点位文件"), cameraLines))
            return false;
        if (!readLines(m_calibTcpFile, QStringLiteral("戳点文件"), tcpLines))
            return false;
    }
    if (needPose
            && !readLines(m_calibPoseFile, QStringLiteral("位姿文件"), poseLines))
        return false;

    folder = dir;
    return true;
}

void ToolsPanel::updateCalibrationResult()
{
    if (m_calibWatcher->isRunning() || m_calibTryAllWatcher->isRunning())
        return;

    QString folder;
    std::vector<QString> cameraLines, poseLines, tcpLines;
    if (!gatherCalibrationInput(folder, cameraLines, poseLines, tcpLines))
        return;
    if (m_sessionActive) {
        m_calibHint->setText(QStringLiteral("当前会话：%1（%2 组数据）")
            .arg(folder).arg(cameraLines.size()));
    }
    runCalibration(folder, cameraLines, poseLines, tcpLines);
}

void ToolsPanel::onCalibrationFinished()
{
    m_calibCalcBtn->setEnabled(true);
    m_calibCalcBtn->setText(QStringLiteral("计算"));
    const auto r = m_calibWatcher->result();
    if (!r.ok) {
        m_calibResult->setPlainText(QStringLiteral("标定失败：%1").arg(r.error));
        m_calibHint->setText(r.error);
        return;
    }

    m_calibResult->setPlainText(CalibrationService::formatResult(r));

    // 位姿格式选错不会报错、只会算错（实测：格式对 ≈0，UR 的轴角当欧拉 ≈30），
    // 所以给一条只提示、不拦截的线索（PROJECT.md §3：质量告警不得拦截）。
    if (r.totalMeanError > CalibrationService::kPoseFormatSuspectError) {
        m_calibHint->setText(QStringLiteral(
            "总平均误差 %1 偏大 —— 位姿格式可能选错（当前：%2 · %3）。"
            "可到「机器人数据格式推算」页的方式 ③ 对照一下。")
            .arg(r.totalMeanError, 0, 'g', 4)
            .arg(CalibrationService::poseFormatName(currentCalibPoseFormat()),
                 currentCalibAngleUnit() == TransformTools::AngleUnit::Radian
                     ? QStringLiteral("弧度") : QStringLiteral("度")));
    }
}

void ToolsPanel::runTryAllPoseFormats()
{
    if (m_calibWatcher->isRunning() || m_calibTryAllWatcher->isRunning())
        return;

    QString folder;
    std::vector<QString> cameraLines, poseLines, tcpLines;
    QString inputError;
    if (!gatherCalibrationInput(folder, cameraLines, poseLines, tcpLines,
                                &inputError)) {
        if (m_inferHint) {
            m_inferHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                           .arg(Theme::ERROR).arg(Theme::FONT_HINT));
            m_inferHint->setText(inputError);
        }
        return;
    }

    const CalibrationService::Params base = calibParams();
    // 眼在手外的戳点标定根本不用机器人拍照位姿（SDK 收到的是空），
    // 格式怎么选都不影响结果 —— 试算 10 遍只会得到 10 行一样的数，别误导。
    if (base.calibType == CalibType::TcpTouch && !base.eyeInHand) {
        m_inferHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                       .arg(Theme::ERROR).arg(Theme::FONT_HINT));
        m_inferHint->setText(QStringLiteral(
            "眼在手外的戳点标定不使用机器人拍照位姿，位姿格式对结果没有影响"));
        return;
    }
    if (poseLines.empty()) {
        m_inferHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                       .arg(Theme::ERROR).arg(Theme::FONT_HINT));
        m_inferHint->setText(QStringLiteral(
            "试算各格式需要机器人拍照位姿：当前没有这一列数据"));
        return;
    }

    const int combinationCount = static_cast<int>(kTryAllPoseFormats.size()) * 2;
    // 标定板模式每种组合都要重跑一遍识别（N 帧 × 组合数），现场可能几分钟。
    if (base.calibType == CalibType::Marker) {
        const auto answer = QMessageBox::question(
            this, QStringLiteral("试算各格式"),
            QStringLiteral(
                "标定板模式下每一种组合都要把识别重跑一遍（共 %1 次），"
                "数据多时可能需要几分钟。期间界面仍可操作，但请勿关闭程序。\n\n"
                "现在开始试算吗？").arg(combinationCount),
            QMessageBox::Yes | QMessageBox::No, QMessageBox::Yes);
        if (answer != QMessageBox::Yes)
            return;
    }

    const RobotDataFormats::Id preset = m_config
        ? m_config->calibPoseFormat() : base.poseFormat;
    const TransformTools::AngleUnit presetUnit = m_config
        ? m_config->calibPoseAngleUnit() : base.poseAngleUnit;

    m_inferTryAllBtn->setEnabled(false);
    m_inferTryAllBtn->setText(QStringLiteral("试算中..."));
    m_inferHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                   .arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));
    m_inferHint->setText(QStringLiteral("正在试算 %1 种组合 …（界面不卡）")
                             .arg(combinationCount));

    m_calibTryAllWatcher->setFuture(QtConcurrent::run(
        [folder, cameraLines, poseLines, tcpLines, base, preset, presetUnit]() {
            struct Row {
                RobotDataFormats::Id fmt;
                TransformTools::AngleUnit unit;
                bool ok = false;
                double mean = 0.0;
                QString error;
            };
            std::vector<Row> rows;
            rows.reserve(static_cast<std::size_t>(kTryAllPoseFormats.size()) * 2);
            for (const auto fmt : kTryAllPoseFormats) {
                for (const auto unit : { TransformTools::AngleUnit::Degree,
                                         TransformTools::AngleUnit::Radian }) {
                    CalibrationService::Params p = base;
                    p.poseFormat = fmt;
                    p.poseAngleUnit = unit;
                    const CalibrationService::Result r = CalibrationService::calibrate(
                        folder, cameraLines, poseLines, tcpLines, p);
                    rows.push_back(Row{ fmt, unit, r.ok, r.totalMeanError, r.error });
                }
            }
            // 升序排总平均误差，失败的一律沉底（误差值本身没有意义）。
            std::stable_sort(rows.begin(), rows.end(), [](const Row& a, const Row& b) {
                if (a.ok != b.ok)
                    return a.ok;
                return a.mean < b.mean;
            });

            auto unitName = [](TransformTools::AngleUnit u) {
                return u == TransformTools::AngleUnit::Radian
                    ? QStringLiteral("弧度") : QStringLiteral("度");
            };

            QString out = QStringLiteral("── 试算各格式（同一份数据，共 %1 种组合）──\n")
                              .arg(rows.size());
            const Row* best = nullptr;
            for (const Row& row : rows) {
                if (!row.ok) {
                    out += QStringLiteral("%1 · %2  失败：%3\n")
                               .arg(CalibrationService::poseFormatName(row.fmt),
                                    unitName(row.unit), row.error);
                    continue;
                }
                if (!best)
                    best = &row;
                const bool isPreset = row.fmt == preset && row.unit == presetUnit;
                out += QStringLiteral("%1 · %2  总平均误差 %3%4\n")
                           .arg(CalibrationService::poseFormatName(row.fmt),
                                unitName(row.unit),
                                QString::number(row.mean, 'g', 4),
                                isPreset ? QStringLiteral("  ←当前预设") : QString());
            }
            if (best) {
                out += QStringLiteral(
                    "\n误差最小的组合最贴近卡片的真实格式：%1 · %2。\n"
                    "未自动改动任何设置 —— 确认后在工具页选好并点「应用」才会生效。")
                    .arg(CalibrationService::poseFormatName(best->fmt),
                         unitName(best->unit));
            }
            return out;
        }));
}

void ToolsPanel::onTryAllFinished()
{
    m_inferTryAllBtn->setText(QStringLiteral("试算各格式"));
    m_inferTryAllBtn->setEnabled(true);
    m_inferHint->clear();
    // 结果写在推算页自己的结果框里（标定页已不再有这个入口）。
    m_inferResult->setPlainText(m_calibTryAllWatcher->result());
    updateInferenceDataLabel();
}

void ToolsPanel::buildTransformPage(QStackedWidget* stack)
{
    auto* page = new QWidget(stack);
    auto* pageLayout = new QVBoxLayout(page);

    auto* group = new QGroupBox(QStringLiteral("坐标转换（走点验证）"), page);
    auto* form = new QFormLayout(group);
    form->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);

    // Mounting mode
    m_mountCombo = new ArrowComboBox(group);
    m_mountCombo->addItem(QStringLiteral("眼在手外（相机固定）"));
    m_mountCombo->addItem(QStringLiteral("眼在手上（相机装在末端）"));
    m_mountCombo->setStyleSheet(Theme::comboBoxStyle());
    form->addRow(QStringLiteral("安装方式"), m_mountCombo);

    // Calibration result matrix: paste 16 row-major values
    m_matInput = makeTextInput(group);
    m_matInput->setObjectName(QStringLiteral("matrix_input"));
    m_matInput->setPlaceholderText(QStringLiteral(
        "16 个数值，英文逗号/空格分隔，行主序，可直接复制粘贴"));
    form->addRow(QStringLiteral("标定结果矩阵"), m_matInput);
    auto* matHint = new QLabel(
        QStringLiteral("4×4 齐次矩阵，行主序（RVC HandEyeSDK 输出）"), group);
    matHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
        .arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));
    form->addRow(QString(), matHint);

    // Camera point
    auto* camRow = new QHBoxLayout();
    camRow->setSpacing(8);
    m_camPointInput = makeTextInput(group);
    m_camPointInput->setObjectName(QStringLiteral("camera_point_input"));
    m_camPointInput->setPlaceholderText(QStringLiteral(
        "x, y, z，英文逗号/空格分隔，可直接复制粘贴"));
    camRow->addWidget(m_camPointInput, 1);
    m_camUnitCombo = new ArrowComboBox(group);
    m_camUnitCombo->addItem(QStringLiteral("mm"));
    m_camUnitCombo->addItem(QStringLiteral("m"));
    m_camUnitCombo->setMinimumWidth(88);
    m_camUnitCombo->setStyleSheet(Theme::comboBoxStyle());
    camRow->addWidget(m_camUnitCombo);
    form->addRow(QStringLiteral("相机系点 (x y z)"), camRow);

    // Robot pose (base->TCP), only needed for eye-in-hand
    m_poseGroup = new QGroupBox(QStringLiteral("机械臂位姿（基座→TCP）"), group);
    auto* poseForm = new QFormLayout(m_poseGroup);

    m_poseInput = makeTextInput(m_poseGroup);
    m_poseInput->setObjectName(QStringLiteral("pose_input"));
    poseForm->addRow(QStringLiteral("位置 + 旋转"), m_poseInput);

    m_poseFormatCombo = new ArrowComboBox(m_poseGroup);
    m_poseFormatCombo->setObjectName(QStringLiteral("pose_format_combo"));
    rebuildFormatCombo(m_poseFormatCombo, false, false, Id::EulerSxyz);
    m_poseFormatCombo->setStyleSheet(Theme::comboBoxStyle());
    poseForm->addRow(QStringLiteral("机器人数据格式"), m_poseFormatCombo);

    m_advancedFormatsCheck = new QCheckBox(
        QStringLiteral("显示高级格式（首尾同轴，如 ZYZ / XYX）"), m_poseGroup);
    poseForm->addRow(QString(), m_advancedFormatsCheck);

    m_angleUnitCombo = new ArrowComboBox(m_poseGroup);
    m_angleUnitCombo->addItem(QStringLiteral("度"));
    m_angleUnitCombo->addItem(QStringLiteral("弧度"));
    m_angleUnitCombo->setStyleSheet(Theme::comboBoxStyle());
    poseForm->addRow(QStringLiteral("角度单位"), m_angleUnitCombo);

    auto* poseUnitRow = new QHBoxLayout();
    poseUnitRow->setSpacing(8);
    poseUnitRow->addWidget(new QLabel(QStringLiteral("位姿位置单位"), m_poseGroup));
    m_poseUnitCombo = new ArrowComboBox(m_poseGroup);
    m_poseUnitCombo->addItem(QStringLiteral("mm"));
    m_poseUnitCombo->addItem(QStringLiteral("m"));
    m_poseUnitCombo->setMinimumWidth(88);
    m_poseUnitCombo->setStyleSheet(Theme::comboBoxStyle());
    poseUnitRow->addWidget(m_poseUnitCombo);
    poseUnitRow->addStretch();
    poseForm->addRow(QString(), poseUnitRow);

    m_rotDescLabel = new QLabel(m_poseGroup);
    m_rotDescLabel->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
        .arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));
    m_rotDescLabel->setWordWrap(true);
    poseForm->addRow(QString(), m_rotDescLabel);

    form->addRow(m_poseGroup);

    // Result row — caption embedded so the values sit right next to "结果".
    auto* resultRow = new QHBoxLayout();
    resultRow->setSpacing(8);
    auto* resultCaption = new QLabel(QStringLiteral("结果"), group);
    resultCaption->setStyleSheet(QStringLiteral(
        "font-size: %1px; color: %2;")
        .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    resultRow->addWidget(resultCaption);
    m_transformResult = new QLabel(QStringLiteral("--"), group);
    m_transformResult->setObjectName(QStringLiteral("transform_result"));
    m_transformResult->setStyleSheet(QStringLiteral(
        "font-size: %1px; font-weight: 600; color: %2;")
        .arg(Theme::FONT_H2).arg(Theme::PRIMARY));
    resultRow->addWidget(m_transformResult);
    resultRow->addStretch();
    m_transformCalcBtn = new QPushButton(QStringLiteral("计算"), group);
    m_transformCalcBtn->setStyleSheet(Theme::primaryButtonStyle());
    resultRow->addWidget(m_transformCalcBtn);
    m_transformCopyBtn = new QPushButton(QStringLiteral("复制"), group);
    m_transformCopyBtn->setStyleSheet(Theme::secondaryButtonStyle());
    resultRow->addWidget(m_transformCopyBtn);
    form->addRow(resultRow);

    // Inline validation hint (operation hint label)
    m_transformHint = new QLabel(group);
    m_transformHint->setObjectName(QStringLiteral("transform_hint"));
    m_transformHint->setStyleSheet(QStringLiteral(
        "color: %1; font-size: %2px;").arg(Theme::ERROR).arg(Theme::FONT_HINT));
    m_transformHint->setWordWrap(true);
    form->addRow(QString(), m_transformHint);

    pageLayout->addWidget(group);
    pageLayout->addStretch();
    stack->addWidget(wrapScrollable(page, stack));

    connect(m_mountCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int index) {
                m_poseGroup->setEnabled(index == 1);
            });
    connect(m_poseFormatCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int) { updatePoseInputHint(); });
    connect(m_angleUnitCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int) { updatePoseInputHint(); });
    connect(m_advancedFormatsCheck, &QCheckBox::toggled, this, [this](bool on) {
        const RobotDataFormats::Id current = comboFormat(m_poseFormatCombo);
        rebuildFormatCombo(m_poseFormatCombo, on, false, current);
        updatePoseInputHint();
    });
    connect(m_transformCalcBtn, &QPushButton::clicked,
            this, &ToolsPanel::updateTransformResult);
    connect(m_transformCopyBtn, &QPushButton::clicked, this, [this]() {
        if (!m_transformValues.isEmpty())
            QApplication::clipboard()->setText(m_transformValues);
    });
    for (QLineEdit* edit : { m_matInput, m_camPointInput, m_poseInput })
        connect(edit, &QLineEdit::textChanged, this, [this](const QString&) {
            m_transformHint->clear();
        });

    m_poseGroup->setEnabled(false);
    updatePoseInputHint();
}

void ToolsPanel::updatePoseInputHint()
{
    const RobotDataFormats::Id fmt = comboFormat(m_poseFormatCombo);
    const RobotDataFormats::Entry& e = RobotDataFormats::entry(fmt);
    const QString unit = m_angleUnitCombo->currentIndex() == 0
                             ? QStringLiteral("度")
                             : QStringLiteral("弧度");

    QString placeholder;
    switch (e.kind) {
    case RobotDataFormats::Kind::Euler:
        placeholder = e.usesAngleUnit
            ? QStringLiteral("px, py, pz, 3 个旋转数（%1，%2）").arg(e.name, unit)
            : QStringLiteral("px, py, pz, 3 个旋转数（%1）").arg(e.name);
        break;
    case RobotDataFormats::Kind::RotationVector:
        placeholder = QStringLiteral("px, py, pz, rx, ry, rz（旋转矢量，%1）").arg(unit);
        break;
    case RobotDataFormats::Kind::Quaternion:
        placeholder = fmt == RobotDataFormats::Id::QuatWxyz
            ? QStringLiteral("px, py, pz, w, x, y, z（四元数 w x y z）")
            : QStringLiteral("px, py, pz, x, y, z, w（四元数 x y z w）");
        break;
    case RobotDataFormats::Kind::Matrix3x3:
        placeholder = fmt == RobotDataFormats::Id::Matrix3x3Col
            ? QStringLiteral("px, py, pz, 旋转矩阵 9 个值（列主序）")
            : QStringLiteral("px, py, pz, 旋转矩阵 9 个值（行主序）");
        break;
    case RobotDataFormats::Kind::Matrix4x4:
        placeholder = QStringLiteral(
            "16 个数值，行主序 4×4（位置取第 4 列，不再另填 px/py/pz）");
        break;
    }
    m_poseInput->setPlaceholderText(placeholder);

    // 统一三行提示：常见机器人 / 原理 / 读法（唯一出处 = RobotDataFormats）。
    QString desc = RobotDataFormats::hint(fmt);
    if (!e.usesAngleUnit)
        desc += QStringLiteral("\n角度单位：该格式不涉及角度单位（上方下拉框已禁用）");
    m_rotDescLabel->setText(desc);

    // 四元数 / 旋转矩阵与“度/弧度”无关，禁用比留着更容易懂。
    if (m_angleUnitCombo)
        m_angleUnitCombo->setEnabled(e.usesAngleUnit);
}

void ToolsPanel::updateTransformResult()
{
    auto fail = [this](const QString& message) {
        m_transformHint->setText(message);
    };

    ToolInputParser::ParseResult mat = ToolInputParser::parseNumberList(
        m_matInput->text().toStdString(), 16);
    if (mat.status != ToolInputParser::ParseStatus::Ok) {
        fail(QStringLiteral("标定结果矩阵：%1").arg(parseErrorText(mat, 16)));
        return;
    }

    ToolInputParser::ParseResult cam = ToolInputParser::parseNumberList(
        m_camPointInput->text().toStdString(), 3);
    if (cam.status != ToolInputParser::ParseStatus::Ok) {
        fail(QStringLiteral("相机系点：%1").arg(parseErrorText(cam, 3)));
        return;
    }

    TransformTools::Mat4 camMat{};
    for (size_t i = 0; i < camMat.size(); ++i)
        camMat[i] = mat.values[i];

    const auto camUnit = m_camUnitCombo->currentIndex() == 0
                             ? TransformTools::LengthUnit::Millimeter
                             : TransformTools::LengthUnit::Meter;
    const double cx = TransformTools::toMillimeters(cam.values[0], camUnit);
    const double cy = TransformTools::toMillimeters(cam.values[1], camUnit);
    const double cz = TransformTools::toMillimeters(cam.values[2], camUnit);
    double bx = 0.0, by = 0.0, bz = 0.0;

    if (m_mountCombo->currentIndex() == 0) {
        TransformTools::eyeToHandPoint(camMat, cx, cy, cz, bx, by, bz);
    } else {
        const RobotDataFormats::Id fmt = comboFormat(m_poseFormatCombo);
        const auto unit = m_angleUnitCombo->currentIndex() == 0
                              ? TransformTools::AngleUnit::Degree
                              : TransformTools::AngleUnit::Radian;
        // 4×4 姿态变换矩阵本身就是一整行位姿（16 个数）；其余格式是
        // “px py pz + 旋转值”。硬凑成 19 个数只会让用户多填一遍位置。
        const bool matrix4 = fmt == RobotDataFormats::Id::Matrix4x4Row;
        const size_t poseCount = matrix4
            ? 16
            : 3 + static_cast<size_t>(RobotDataFormats::valueCount(fmt));
        ToolInputParser::ParseResult pose = ToolInputParser::parseNumberList(
            m_poseInput->text().toStdString(), poseCount);
        if (pose.status != ToolInputParser::ParseStatus::Ok) {
            fail(QStringLiteral("机械臂位姿：%1").arg(parseErrorText(pose, poseCount)));
            return;
        }

        const auto poseUnit = m_poseUnitCombo->currentIndex() == 0
                                  ? TransformTools::LengthUnit::Millimeter
                                  : TransformTools::LengthUnit::Meter;
        TransformTools::Mat4 baseToTcp{};
        if (matrix4) {
            std::vector<double> values(pose.values.begin(), pose.values.end());
            baseToTcp = RobotDataFormats::poseToMat4(
                0, 0, 0, fmt, unit, values);
            // 位置在第 4 列（0 基下标 3/7/11），按「位姿位置单位」换算。
            baseToTcp[3] = TransformTools::toMillimeters(baseToTcp[3], poseUnit);
            baseToTcp[7] = TransformTools::toMillimeters(baseToTcp[7], poseUnit);
            baseToTcp[11] = TransformTools::toMillimeters(baseToTcp[11], poseUnit);
        } else {
            const double px = TransformTools::toMillimeters(pose.values[0], poseUnit);
            const double py = TransformTools::toMillimeters(pose.values[1], poseUnit);
            const double pz = TransformTools::toMillimeters(pose.values[2], poseUnit);
            std::vector<double> rotVals(pose.values.begin() + 3, pose.values.end());
            baseToTcp = RobotDataFormats::poseToMat4(
                px, py, pz, fmt, unit, rotVals);
        }
        TransformTools::eyeInHandPoint(camMat, baseToTcp, cx, cy, cz, bx, by, bz);
    }

    m_transformHint->clear();
    m_transformValues = QStringLiteral("%1, %2, %3")
        .arg(bx, 0, 'f', 3).arg(by, 0, 'f', 3).arg(bz, 0, 'f', 3);
    m_transformResult->setText(m_transformValues);
}

void ToolsPanel::buildFormatInferencePage(QStackedWidget* stack)
{
    auto* page = new QWidget(stack);
    auto* pageLayout = new QVBoxLayout(page);

    auto* group = new QGroupBox(QStringLiteral("机器人数据格式推算"), page);
    auto* form = new QFormLayout(group);
    form->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
    m_inferPage = page;

    auto* intro = new QLabel(QStringLiteral(
        "目的：只确认示教器上那 3 个旋转数属于 24 种欧拉约定中的哪一种。"
        "角度单位、四元数顺序不在这里推断 —— 这些一般示教器或手册会直接写明。\n"
        "推荐做法：让机器人停在一个三轴都不为 0 的普通姿态，只绕基坐标的一根轴转 15°~60°，"
        "记下转动前后各一组数，并在「点动轴」里选你实际点的那根轴；"
        "最好再做一组绕另一根基轴的点动。\n"
        "实验 2、3 可留空：只做一组也能出结果，若出现多个候选，再补一组绕不同轴的点动。"), group);
    intro->setWordWrap(true);
    intro->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
        .arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));
    form->addRow(intro);

    m_inferMethodCombo = new ArrowComboBox(group);
    m_inferMethodCombo->setObjectName(QStringLiteral("format_infer_method"));
    m_inferMethodCombo->addItem(QStringLiteral("① 绕基坐标轴点动实验（推荐）"));
    m_inferMethodCombo->addItem(QStringLiteral("② 绕工具坐标轴点动实验"));
    m_inferMethodCombo->addItem(QStringLiteral("③ 用已有标定数据按残差排序"));
    m_inferMethodCombo->setStyleSheet(Theme::comboBoxStyle());
    form->addRow(QStringLiteral("确认方式"), m_inferMethodCombo);

    m_inferUnitCombo = new ArrowComboBox(group);
    m_inferUnitCombo->addItem(QStringLiteral("度"));
    m_inferUnitCombo->addItem(QStringLiteral("弧度"));
    m_inferUnitCombo->setStyleSheet(Theme::comboBoxStyle());
    // 包一层控件：方式 ③ 时整行（标签 + 下拉框）一起隐藏，而不是灰着占位。
    m_inferUnitRow = new QWidget(group);
    auto* unitRowLayout = new QHBoxLayout(m_inferUnitRow);
    unitRowLayout->setContentsMargins(0, 0, 0, 0);
    unitRowLayout->addWidget(m_inferUnitCombo);
    form->addRow(QStringLiteral("角度单位"), m_inferUnitRow);

    auto* expGroup = new QGroupBox(
        QStringLiteral("点动实验（每行贴 3 个旋转数，或整行 6 个位姿数 —— 只取后 3 个）"),
        group);
    m_inferExperiments = expGroup;
    auto* grid = new QGridLayout(expGroup);
    grid->setHorizontalSpacing(8);
    auto* axisHeader = new QLabel(QStringLiteral("点动轴"), expGroup);
    auto* beforeHeader = new QLabel(QStringLiteral("转动前"), expGroup);
    auto* afterHeader = new QLabel(QStringLiteral("转动后"), expGroup);
    grid->addWidget(axisHeader, 0, 1);
    grid->addWidget(beforeHeader, 0, 2);
    grid->addWidget(afterHeader, 0, 3);
    // 前两行默认绕不同轴：只转同一根轴分不开轴顺序循环换名的那几种约定。
    const std::array<int, 3> defaultAxis { 0, 2, 1 };   // X, Z, Y
    for (int i = 0; i < 3; ++i) {
        auto* label = new QLabel(QStringLiteral("实验 %1").arg(i + 1), expGroup);
        auto* axis = new ArrowComboBox(expGroup);
        axis->setObjectName(QStringLiteral("format_infer_axis_%1").arg(i + 1));
        axis->addItem(QStringLiteral("X 轴"));
        axis->addItem(QStringLiteral("Y 轴"));
        axis->addItem(QStringLiteral("Z 轴"));
        axis->setCurrentIndex(defaultAxis[static_cast<std::size_t>(i)]);
        axis->setStyleSheet(Theme::comboBoxStyle());
        m_inferAxis[static_cast<std::size_t>(i)] = axis;
        m_inferBefore[static_cast<std::size_t>(i)] = makeTextInput(expGroup);
        m_inferAfter[static_cast<std::size_t>(i)] = makeTextInput(expGroup);
        m_inferBefore[static_cast<std::size_t>(i)]->setPlaceholderText(
            QStringLiteral("例如 12.3 -45.6 78.9"));
        m_inferAfter[static_cast<std::size_t>(i)]->setPlaceholderText(
            QStringLiteral("只填一组的可留空"));
        grid->addWidget(label, i + 1, 0);
        grid->addWidget(axis, i + 1, 1);
        grid->addWidget(m_inferBefore[static_cast<std::size_t>(i)], i + 1, 2);
        grid->addWidget(m_inferAfter[static_cast<std::size_t>(i)], i + 1, 3);
    }
    grid->setColumnStretch(2, 1);
    grid->setColumnStretch(3, 1);
    form->addRow(expGroup);

    // 方式 ③：原本在手眼标定页的「试算各格式」整体迁到这里（用户 2026-10-19）。
    // 数据来源原先必须去「手眼标定」页设置 —— 用户反馈那样得来回切页；本页
    // 现在有一份与那一页双向同步的输入组：在哪一页改都行，两边始终一致。
    auto* residual = new QGroupBox(
        QStringLiteral("用已有标定数据按残差排序"), group);
    m_inferResidualGroup = residual;
    auto* residualLayout = new QVBoxLayout(residual);
    auto* residualNote = new QLabel(QStringLiteral(
        "把 5 种常见约定 × 度/弧度各算一遍，按 SDK 总平均误差从低到高列出。"
        "只给参考，不会自动改任何设置。"), residual);
    residualNote->setWordWrap(true);
    residualNote->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                    .arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));
    residualLayout->addWidget(residualNote);

    auto* dataGroup = new QGroupBox(
        QStringLiteral("标定数据（与「手眼标定」页同步）"), residual);
    m_inferDataGroup = dataGroup;
    auto* dataForm = new QFormLayout(dataGroup);
    dataForm->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);
    m_inferDataForm = dataForm;

    // 数据文件夹（与标定页同一格值的镜像）
    auto* inferDirRow = new QHBoxLayout();
    inferDirRow->setSpacing(8);
    m_inferDirEdit = makeTextInput(dataGroup);
    m_inferDirEdit->setObjectName(QStringLiteral("format_infer_dir"));
    m_inferDirEdit->setPlaceholderText(QStringLiteral("选择会话文件夹"));
    inferDirRow->addWidget(m_inferDirEdit, 1);
    auto* inferDirBrowse = new QPushButton(QStringLiteral("浏览"), dataGroup);
    inferDirBrowse->setStyleSheet(Theme::secondaryButtonStyle());
    inferDirRow->addWidget(inferDirBrowse);
    dataForm->addRow(QStringLiteral("数据文件夹"), inferDirRow);

    auto addInferFileRow = [this, dataForm, dataGroup](const QString& label,
                                                       const QString& objName,
                                                       QLineEdit*& edit,
                                                       QWidget*& rowWidget,
                                                       const QString& title) {
        edit = makeTextInput(dataGroup);
        edit->setObjectName(objName);
        auto* row = new QHBoxLayout();
        row->setSpacing(8);
        row->addWidget(edit, 1);
        auto* browse = new QPushButton(QStringLiteral("浏览"), dataGroup);
        browse->setStyleSheet(Theme::secondaryButtonStyle());
        row->addWidget(browse);
        rowWidget = new QWidget(dataGroup);
        rowWidget->setLayout(row);
        dataForm->addRow(label, rowWidget);
        connect(browse, &QPushButton::clicked, this,
                [this, edit, title]() { chooseCalibrationFile(edit, title); });
    };
    addInferFileRow(QStringLiteral("位姿文件"), QStringLiteral("format_infer_pose_file"),
                    m_inferPoseFileEdit, m_inferPoseFileRow,
                    QStringLiteral("选择机器人位姿文件"));
    addInferFileRow(QStringLiteral("相机点位文件"), QStringLiteral("format_infer_camera_file"),
                    m_inferCameraFileEdit, m_inferCameraFileRow,
                    QStringLiteral("选择相机点位文件"));
    addInferFileRow(QStringLiteral("戳点文件"), QStringLiteral("format_infer_tcp_file"),
                    m_inferTcpFileEdit, m_inferTcpFileRow,
                    QStringLiteral("选择戳点文件"));

    m_inferCalibTypeCombo = new ArrowComboBox(dataGroup);
    m_inferCalibTypeCombo->addItem(QStringLiteral("标定板识别（同心圆 / 黑白圆）"));
    m_inferCalibTypeCombo->addItem(QStringLiteral("戳点标定（TCP touch）"));
    m_inferCalibTypeCombo->setStyleSheet(Theme::comboBoxStyle());
    dataForm->addRow(QStringLiteral("标定方式"), m_inferCalibTypeCombo);

    m_inferEyeCombo = new ArrowComboBox(dataGroup);
    m_inferEyeCombo->addItem(QStringLiteral("眼在手外（相机固定）"));
    m_inferEyeCombo->addItem(QStringLiteral("眼在手上（相机装在末端）"));
    m_inferEyeCombo->setStyleSheet(Theme::comboBoxStyle());
    dataForm->addRow(QStringLiteral("安装方式"), m_inferEyeCombo);

    m_inferMarkerCombo = new ArrowComboBox(dataGroup);
    m_inferMarkerCombo->addItem(QStringLiteral("同心圆"));
    m_inferMarkerCombo->addItem(QStringLiteral("黑白圆（标定板）"));
    m_inferMarkerCombo->setStyleSheet(Theme::comboBoxStyle());
    dataForm->addRow(QStringLiteral("标定板类型"), m_inferMarkerCombo);

    m_inferPoseUnitCombo = new ArrowComboBox(dataGroup);
    m_inferPoseUnitCombo->addItem(QStringLiteral("mm"));
    m_inferPoseUnitCombo->addItem(QStringLiteral("m"));
    m_inferPoseUnitCombo->setStyleSheet(Theme::comboBoxStyle());
    dataForm->addRow(QStringLiteral("位姿位置单位"), m_inferPoseUnitCombo);

    m_inferAutoRemoveCheck = new QCheckBox(
        QStringLiteral("自动剔除大误差数据（SDK 内置）"), dataGroup);
    dataForm->addRow(QString(), m_inferAutoRemoveCheck);

    residualLayout->addWidget(dataGroup);

    m_inferDataLabel = new QLabel(residual);
    m_inferDataLabel->setObjectName(QStringLiteral("format_infer_data_note"));
    m_inferDataLabel->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                        .arg(Theme::TEXT_BODY).arg(Theme::FONT_HINT));
    m_inferDataLabel->setWordWrap(true);
    residualLayout->addWidget(m_inferDataLabel);

    auto* residualButtons = new QHBoxLayout();
    residualButtons->setSpacing(8);
    m_inferSessionBtn = new QPushButton(QStringLiteral("用当前会话"), residual);
    m_inferSessionBtn->setStyleSheet(Theme::secondaryButtonStyle());
    m_inferSessionBtn->setToolTip(QStringLiteral(
        "载入当前会话的数据，载入后直接开始试算"));
    residualButtons->addWidget(m_inferSessionBtn);
    m_inferTryAllBtn = new QPushButton(QStringLiteral("试算各格式"), residual);
    m_inferTryAllBtn->setStyleSheet(Theme::primaryButtonStyle());
    m_inferTryAllBtn->setToolTip(QStringLiteral(
        "同一份数据把 5 种常见位姿格式 x 度/弧度 各算一遍，按总平均误差排序"));
    residualButtons->addWidget(m_inferTryAllBtn);
    residualButtons->addStretch();
    residualLayout->addLayout(residualButtons);
    residual->setVisible(false);
    form->addRow(residual);

    auto* btnRow = new QHBoxLayout();
    btnRow->setSpacing(8);
    m_inferRunBtn = new QPushButton(QStringLiteral("推算"), group);
    m_inferRunBtn->setStyleSheet(Theme::primaryButtonStyle());
    btnRow->addWidget(m_inferRunBtn);
    m_inferApplyBtn = new QPushButton(QStringLiteral("应用为全局预设"), group);
    m_inferApplyBtn->setStyleSheet(Theme::secondaryButtonStyle());
    m_inferApplyBtn->setEnabled(false);
    m_inferApplyBtn->setToolTip(QStringLiteral(
        "把唯一判定的格式写进 AppConfig：手眼标定页与主界面「计算」都按它读卡片"));
    btnRow->addWidget(m_inferApplyBtn);
    btnRow->addStretch();
    // 包一层控件：方法 ③ 用不到「推算 / 应用」，整行隐藏（用户 2026-10-19 反馈）。
    m_inferActionRow = new QWidget(group);
    m_inferActionRow->setLayout(btnRow);
    form->addRow(QString(), m_inferActionRow);

    m_inferHint = new QLabel(group);
    m_inferHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
        .arg(Theme::ERROR).arg(Theme::FONT_HINT));
    m_inferHint->setWordWrap(true);
    form->addRow(QString(), m_inferHint);

    m_inferResult = new QTextEdit(group);
    m_inferResult->setObjectName(QStringLiteral("format_infer_result"));
    m_inferResult->setReadOnly(true);
    m_inferResult->setMinimumHeight(220);
    m_inferResult->setStyleSheet(QStringLiteral(
        "background: %1; border: 1px solid %2; border-radius: 4px; "
        "font-size: %3px; color: %4; font-family: Consolas, monospace;")
        .arg(Theme::BG_CARD).arg(Theme::BORDER_DEFAULT)
        .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    form->addRow(QStringLiteral("结果"), m_inferResult);

    pageLayout->addWidget(group);
    pageLayout->addStretch();
    stack->addWidget(wrapScrollable(page, stack));

    connect(m_inferRunBtn, &QPushButton::clicked,
            this, &ToolsPanel::updateFormatInference);
    connect(m_inferApplyBtn, &QPushButton::clicked,
            this, &ToolsPanel::applyInferredFormat);
    connect(m_inferSessionBtn, &QPushButton::clicked, this, [this]() {
        // 复用标定页的会话入口；标志位让载入完成后直接跑试算。
        m_sessionForTryAll = true;
        emit calibrationSessionRequested();
    });
    connect(inferDirBrowse, &QPushButton::clicked, this, [this]() {
        const QString start = m_calibDir ? m_calibDir->text().trimmed() : QString();
        const QString dir = QFileDialog::getExistingDirectory(
            this, QStringLiteral("选择标定数据文件夹"), start);
        if (!dir.isEmpty())
            m_inferDirEdit->setText(QDir::toNativeSeparators(dir));
    });
    connect(m_inferTryAllBtn, &QPushButton::clicked,
            this, &ToolsPanel::runTryAllPoseFormats);

    // ── 与手眼标定页双向同步 ─────────────────────────────────────────
    // 两页各有一份控件，但只有一份值：改任何一边，另一边立刻跟着走。
    // 相等就跳过，避免 setText → textChanged → setText 的无限往返。
    auto linkEdit = [this](QLineEdit* a, QLineEdit* b) {
        QObject::connect(a, &QLineEdit::textChanged, b, [b](const QString& t) {
            if (b->text() != t)
                b->setText(t);
        });
        QObject::connect(b, &QLineEdit::textChanged, a, [a](const QString& t) {
            if (a->text() != t)
                a->setText(t);
        });
    };
    auto linkCombo = [this](QComboBox* a, QComboBox* b) {
        const auto sync = [this](QComboBox* from, QComboBox* to) {
            QObject::connect(from, QOverload<int>::of(&QComboBox::currentIndexChanged),
                             to, [to](int i) {
                                 if (to->currentIndex() != i)
                                     to->setCurrentIndex(i);
                             });
        };
        sync(a, b);
        sync(b, a);
    };

    // 先把标定页的当前值抄过来，再连双向线 —— 否则初始状态会缺一部分。
    m_inferDirEdit->setText(m_calibDir->text());
    m_inferPoseFileEdit->setText(m_calibPoseFile->text());
    m_inferCameraFileEdit->setText(m_calibCameraFile->text());
    m_inferTcpFileEdit->setText(m_calibTcpFile->text());
    m_inferCalibTypeCombo->setCurrentIndex(m_calibTypeCombo->currentIndex());
    m_inferEyeCombo->setCurrentIndex(m_calibEyeCombo->currentIndex());
    m_inferMarkerCombo->setCurrentIndex(m_calibMarkerCombo->currentIndex());
    m_inferPoseUnitCombo->setCurrentIndex(m_calibPoseUnitCombo->currentIndex());
    m_inferAutoRemoveCheck->setChecked(m_calibAutoRemove->isChecked());

    linkEdit(m_inferDirEdit, m_calibDir);
    linkEdit(m_inferPoseFileEdit, m_calibPoseFile);
    linkEdit(m_inferCameraFileEdit, m_calibCameraFile);
    linkEdit(m_inferTcpFileEdit, m_calibTcpFile);
    linkCombo(m_inferCalibTypeCombo, m_calibTypeCombo);
    linkCombo(m_inferEyeCombo, m_calibEyeCombo);
    linkCombo(m_inferMarkerCombo, m_calibMarkerCombo);
    linkCombo(m_inferPoseUnitCombo, m_calibPoseUnitCombo);
    QObject::connect(m_inferAutoRemoveCheck, &QCheckBox::toggled,
                     m_calibAutoRemove, &QCheckBox::setChecked);
    QObject::connect(m_calibAutoRemove, &QCheckBox::toggled,
                     m_inferAutoRemoveCheck, &QCheckBox::setChecked);

    // 改本页的标定方式/安装方式 → 本页行显隐；同步接线会顺带更新标定页。
    for (QComboBox* combo : { m_inferCalibTypeCombo, m_inferEyeCombo })
        QObject::connect(combo, QOverload<int>::of(&QComboBox::currentIndexChanged),
                         this, [this](int) {
                             m_inferHint->clear();
                             m_inferBestValid = false;
                             m_inferApplyBtn->setEnabled(false);
                             updateInferenceInputVisibility();
                             updateInferenceDataLabel();
                         });
    // 其余输入变了：清提示并刷新数据来源说明（此时同步线已把标定页改好）。
    for (QLineEdit* edit : { m_inferDirEdit, m_inferPoseFileEdit,
                             m_inferCameraFileEdit, m_inferTcpFileEdit }) {
        QObject::connect(edit, &QLineEdit::textChanged, this, [this](const QString&) {
            m_inferHint->clear();
            updateInferenceDataLabel();
        });
    }
    updateInferenceInputVisibility();

    connect(m_inferMethodCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int index) {
                const bool experiment = index != 2;
                m_inferExperiments->setVisible(experiment);
                // 方法 ③ 不看角度单位，也不显示「推算 / 应用」：整行藏掉，
                // 而不是留个灰按钮让人猜为什么点不动（用户 2026-10-19 反馈）。
                if (m_inferUnitRow)
                    m_inferUnitRow->setVisible(experiment);
                if (m_inferActionRow)
                    m_inferActionRow->setVisible(experiment);
                m_inferRunBtn->setEnabled(experiment);
                if (m_inferResidualGroup)
                    m_inferResidualGroup->setVisible(!experiment);
                m_inferHint->clear();
                m_inferBestValid = false;
                m_inferApplyBtn->setEnabled(false);
                if (!experiment) {
                    updateInferenceDataLabel();
                    m_inferResult->setPlainText(QStringLiteral(
                        "方式 ③：用已经采好的手眼标定数据，把常见格式各算一遍，"
                        "按 SDK 的总平均误差排序。\n\n"
                        "先选数据来源（「用当前会话」或在上面的输入组里选文件夹与文件），"
                        "再点「试算各格式」。误差最小的那一行就是最贴近卡片的格式。\n\n"
                        "试算覆盖 5 种常见约定（sXYZ / rZYX / rZYZ / rXYZ / 轴角）× 度/弧度；"
                        "若是这 5 种以外的约定，请用方式 ①② 的点动实验 —— 它能判全部 24 种。\n\n"
                        "这里的标定数据与「手眼标定」页是同一份设置，在哪一页改都一样。"));
                }
            });
    for (int i = 0; i < 3; ++i) {
        for (QLineEdit* edit : { m_inferBefore[static_cast<std::size_t>(i)],
                                 m_inferAfter[static_cast<std::size_t>(i)] }) {
            connect(edit, &QLineEdit::textChanged, this, [this](const QString&) {
                m_inferHint->clear();
                m_inferBestValid = false;
                m_inferApplyBtn->setEnabled(false);
            });
        }
    }
}

void ToolsPanel::updateFormatInference()
{
    const int method = m_inferMethodCombo ? m_inferMethodCombo->currentIndex() : 0;
    if (method == 2)
        return;   // 方式 ③ 由本页的「试算各格式」执行，不走点动推断

    m_inferBestValid = false;
    m_inferApplyBtn->setEnabled(false);

    // 同一个标签既报错也报成功：颜色跟着结论走，别让成功也红着。
    auto setHint = [this](const QString& text, const char* color) {
        m_inferHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                       .arg(color).arg(Theme::FONT_HINT));
        m_inferHint->setText(text);
    };

    const auto unit = m_inferUnitCombo->currentIndex() == 0
                          ? TransformTools::AngleUnit::Degree
                          : TransformTools::AngleUnit::Radian;
    const auto frame = method == 0 ? RobotDataFormats::JogFrame::Base
                                   : RobotDataFormats::JogFrame::Tool;
    const QString frameName = method == 0 ? QStringLiteral("基坐标")
                                          : QStringLiteral("工具坐标");

    std::vector<RobotDataFormats::PosePair> pairs;
    QStringList jogAxes;
    QStringList errors;
    const std::array<RobotDataFormats::Axis, 3> axes {
        RobotDataFormats::Axis::X, RobotDataFormats::Axis::Y,
        RobotDataFormats::Axis::Z };
    for (int i = 0; i < 3; ++i) {
        const QString before = m_inferBefore[static_cast<std::size_t>(i)]->text().trimmed();
        const QString after = m_inferAfter[static_cast<std::size_t>(i)]->text().trimmed();
        if (before.isEmpty() && after.isEmpty())
            continue;
        if (before.isEmpty() || after.isEmpty()) {
            errors << QStringLiteral("实验 %1 只填了一半").arg(i + 1);
            continue;
        }
        RobotDataFormats::PosePair pair;
        if (!parseRotationTriple(before, pair.before)) {
            errors << QStringLiteral("实验 %1 转动前：要 3 或 6 个数").arg(i + 1);
            continue;
        }
        if (!parseRotationTriple(after, pair.after)) {
            errors << QStringLiteral("实验 %1 转动后：要 3 或 6 个数").arg(i + 1);
            continue;
        }
        const int axisIndex = m_inferAxis[static_cast<std::size_t>(i)]
            ? m_inferAxis[static_cast<std::size_t>(i)]->currentIndex() : 0;
        pair.jogAxis = axes[static_cast<std::size_t>(
            axisIndex >= 0 && axisIndex < 3 ? axisIndex : 0)];
        jogAxes << QStringLiteral("XYZ").mid(axisIndex, 1);
        pairs.push_back(pair);
    }

    if (!errors.isEmpty()) {
        setHint(errors.join(QStringLiteral("；")), Theme::ERROR);
        return;
    }
    if (pairs.empty()) {
        setHint(QStringLiteral("至少填一组完整的实验：转动前 + 转动后。"),
                Theme::ERROR);
        return;
    }

    const std::vector<RobotDataFormats::Candidate> ranked =
        RobotDataFormats::inferEulerConventions(pairs, unit, frame);

    std::vector<RobotDataFormats::Candidate> matched;
    std::vector<RobotDataFormats::Candidate> missed;
    for (const auto& c : ranked)
        (c.axisAligned ? matched : missed).push_back(c);

    QString out = QStringLiteral("── 推算结果（%1点动，%2 组实验，点动轴 %3）──\n")
                      .arg(frameName)
                      .arg(pairs.size())
                      .arg(jogAxes.join(QStringLiteral(" / ")));

    auto name = [](RobotDataFormats::Id id) {
        return RobotDataFormats::displayName(id);
    };

    if (matched.size() == 1) {
        m_inferBest = matched.front().id;
        m_inferBestValid = true;
        m_inferBestUnit = unit;
        out += QStringLiteral("✔ 唯一匹配：%1\n   %2\n")
                   .arg(name(m_inferBest), matched.front().detail);
        out += QStringLiteral(
            "\n判定依据：按这个约定读那 3 个数时，两次姿态的相对旋转正好绕基轴/工具轴，"
            "\"转了几度、绕哪根轴\"都能对上。\n");
        if (!missed.empty()) {
            out += QStringLiteral("\n其它候选（最近的一行也偏差很大）：\n");
            const int n = std::min<int>(3, static_cast<int>(missed.size()));
            for (int i = 0; i < n; ++i) {
                const auto& c = missed[static_cast<std::size_t>(i)];
                out += QStringLiteral("  ✘ %1 — %2\n").arg(name(c.id), c.detail);
            }
        }
    } else if (matched.empty()) {
        out += QStringLiteral(
            "✘ 24 种欧拉约定里没有一种能让相对旋转落在基轴/工具轴上。\n\n"
            "按顺序检查：\n"
            "  1. 角度单位选对了吗（度 / 弧度）？\n"
            "  2. 点动方式选对了吗（基坐标 / 工具坐标）？\n"
            "  3. 两次读数之间，机器人确实只绕一根轴转了吗？\n"
            "  4. 转角是否在 5°~175° 之间？太小或接近 180° 都不稳定。\n"
            "  5. 起始姿态是否过于特殊（某个角接近 0 或中间角接近 ±90°）？"
            "换一个三轴都不为 0 的普通姿态重做。\n");
        const int n = std::min<int>(5, static_cast<int>(missed.size()));
        if (n > 0) {
            out += QStringLiteral("\n最接近的候选（供参考）：\n");
            for (int i = 0; i < n; ++i) {
                const auto& c = missed[static_cast<std::size_t>(i)];
                out += QStringLiteral("  %1 — %2\n").arg(name(c.id), c.detail);
            }
        }
    } else {
        out += QStringLiteral("⚠ 有 %1 种约定都通过了判据，还不能唯一确定：\n")
                   .arg(matched.size());
        for (const auto& c : matched)
            out += QStringLiteral("  ✔ %1 — %2\n").arg(name(c.id), c.detail);
        out += QStringLiteral(
            "\n再做一组点动：绕另一根基轴（这次绕 X，下次就绕 Z），"
            "转角仍取 15°~60°，起始姿态让三轴都不为 0。\n"
            "两个方向的实验合在一起一般只剩一种候选。");
    }

    m_inferResult->setPlainText(out);
    m_inferApplyBtn->setEnabled(m_inferBestValid);
    if (m_inferBestValid)
        setHint(QStringLiteral("判定唯一，可以点「应用为全局预设」。"), Theme::SUCCESS);
    else
        setHint(QString(), Theme::TEXT_HINT);
}

void ToolsPanel::updateInferenceInputVisibility()
{
    if (!m_inferDataForm || !m_inferCalibTypeCombo || !m_inferEyeCombo)
        return;

    const bool tcp = m_inferCalibTypeCombo->currentIndex() == 1;
    const bool eyeInHand = m_inferEyeCombo->currentIndex() == 1;
    // 与 updateCalibrationModeVisibility 同一套判据（见 DataInputArea 卡片）。
    const bool needPose = !tcp || eyeInHand;

    auto rowVisible = [this](QWidget* field, bool on) {
        if (!field)
            return;
        if (QWidget* label = m_inferDataForm->labelForField(field))
            label->setVisible(on);
        field->setVisible(on);
    };

    rowVisible(m_inferPoseFileRow, needPose);
    rowVisible(m_inferCameraFileRow, tcp);
    rowVisible(m_inferTcpFileRow, tcp);
    rowVisible(m_inferMarkerCombo, !tcp);
    rowVisible(m_inferPoseUnitCombo, needPose);
}

void ToolsPanel::updateInferenceDataLabel()
{
    if (!m_inferDataLabel)
        return;
    if (m_sessionActive) {
        m_inferDataLabel->setText(QStringLiteral("数据来源：当前会话（%1）")
                                      .arg(m_sessionFolder));
        return;
    }
    const QString dir = m_calibDir ? m_calibDir->text().trimmed() : QString();
    if (!dir.isEmpty()) {
        m_inferDataLabel->setText(QStringLiteral("数据来源：文件夹（%1）")
                                      .arg(QDir::toNativeSeparators(dir)));
        return;
    }
    m_inferDataLabel->setText(QStringLiteral(
        "数据来源：尚未选择。点「用当前会话」，或用上方「数据文件夹」指定标定数据目录。"));
}

void ToolsPanel::applyInferredFormat()
{
    if (!m_inferBestValid || !m_config)
        return;

    m_config->setCalibPoseFormat(m_inferBest, m_inferBestUnit);

    // 标定页的下拉框跟着走（它读的是同一份 AppConfig）。
    if (m_calibFormatCombo) {
        const bool advanced =
            RobotDataFormats::tier(m_inferBest) == RobotDataFormats::Tier::Advanced;
        if (m_calibAdvancedCheck)
            m_calibAdvancedCheck->setChecked(advanced);
        rebuildFormatCombo(m_calibFormatCombo, advanced, true, m_inferBest);
        m_calibAngleUnitCombo->setCurrentIndex(
            m_inferBestUnit == TransformTools::AngleUnit::Radian ? 1 : 0);
        updateCalibFormatHint();
    }

    const QString unitName = m_inferBestUnit == TransformTools::AngleUnit::Radian
                                 ? QStringLiteral("弧度") : QStringLiteral("度");
    m_inferHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                   .arg(Theme::SUCCESS).arg(Theme::FONT_HINT));
    m_inferHint->setText(QStringLiteral("已应用：%1 · %2。标定页与主界面「计算」都按它读卡片。")
                             .arg(RobotDataFormats::displayName(m_inferBest), unitName));
    emit logMessage(QStringLiteral("[数据格式] 推算结果已应用为全局预设：%1 · %2")
                        .arg(RobotDataFormats::displayName(m_inferBest), unitName));
}

void ToolsPanel::buildRobotCommPage(QStackedWidget* stack)
{
    auto* page = new QWidget(stack);
    auto* pageLayout = new QVBoxLayout(page);

    auto* group = new QGroupBox(QStringLiteral("机器人通信"), page);
    auto* form = new QFormLayout(group);
    form->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);

    // Protocol + connection status
    auto* protoRow = new QHBoxLayout();
    protoRow->setSpacing(8);
    m_robotProtocol = new ArrowComboBox(group);
    m_robotProtocol->addItem(QStringLiteral("Modbus TCP"));
    m_robotProtocol->addItem(QStringLiteral("UR Realtime (30003)"));
    m_robotProtocol->addItem(QStringLiteral("博纳斯(纳博特) JSON/TCP"));
    // 用户反馈 7：埃夫特走 EfortSDK（第四种协议，index 3 固定不变）。
    m_robotProtocol->addItem(QStringLiteral("埃夫特（EfortSDK）"));
    // 2026-10-10：UR 的新口（RTDE, 30004）。追加在末尾，前面的 index 不动。
    m_robotProtocol->addItem(QStringLiteral("UR RTDE (30004)"));
    m_robotProtocol->setStyleSheet(Theme::comboBoxStyle());
    protoRow->addWidget(m_robotProtocol, 1);
    m_robotStatus = new QLabel(QStringLiteral("未连接"), group);
    m_robotStatus->setStyleSheet(QStringLiteral(
        "font-size: %1px; color: %2;")
        .arg(Theme::FONT_HINT).arg(Theme::TEXT_HINT));
    protoRow->addWidget(m_robotStatus);
    form->addRow(QStringLiteral("协议"), protoRow);

    // Host + port
    auto* hostRow = new QHBoxLayout();
    hostRow->setSpacing(8);
    m_robotHost = makeTextInput(group);
    m_robotHost->setText(QStringLiteral("192.168.0.1"));
    m_robotHost->setPlaceholderText(QStringLiteral("机器人 IP 地址"));
    hostRow->addWidget(m_robotHost, 1);
    m_robotPort = new QSpinBox(group);
    m_robotPort->setRange(1, 65535);
    m_robotPort->setValue(502);
    m_robotPort->setStyleSheet(Theme::spinBoxStyle());
    hostRow->addWidget(m_robotPort);
    form->addRow(QStringLiteral("IP / 端口"), hostRow);

    // 埃夫特专用的一行提示：只在"输入里带了 :端口"时出现（平时隐藏）。
    // 客户给的地址常常写成 "192.168.0.1:8003"，直接把整串喂给 SDK 会连到另一个 IP。
    m_robotHostNote = new QLabel(group);
    m_robotHostNote->setWordWrap(true);
    m_robotHostNote->setStyleSheet(QStringLiteral(
        "color: %1; font-size: %2px;")
        .arg(Theme::WARNING).arg(Theme::FONT_HINT));
    m_robotHostNote->setVisible(false);
    form->addRow(QString(), m_robotHostNote);

    // Modbus-only fields, grouped so they can be hidden together for UR.
    m_modbusFieldsWidget = new QWidget(group);
    auto* modbusLayout = new QFormLayout(m_modbusFieldsWidget);
    modbusLayout->setContentsMargins(0, 0, 0, 0);
    modbusLayout->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);

    // Format + scale
    auto* fmtRow = new QHBoxLayout();
    fmtRow->setSpacing(8);
    m_robotFormat = new ArrowComboBox(m_modbusFieldsWidget);
    m_robotFormat->addItem(QStringLiteral("Float32"));
    m_robotFormat->addItem(QStringLiteral("Int32×系数"));
    m_robotFormat->addItem(QStringLiteral("Int16×系数"));
    m_robotFormat->setStyleSheet(Theme::comboBoxStyle());
    fmtRow->addWidget(m_robotFormat, 1);
    m_robotScale = makeTextInput(m_modbusFieldsWidget);
    m_robotScale->setText(QStringLiteral("1.0"));
    m_robotScale->setFixedWidth(72);
    fmtRow->addWidget(m_robotScale);
    modbusLayout->addRow(QStringLiteral("格式 / 系数"), fmtRow);

    // Start address + unit id
    auto* addrRow = new QHBoxLayout();
    addrRow->setSpacing(8);
    m_robotStartAddr = new QSpinBox(m_modbusFieldsWidget);
    m_robotStartAddr->setRange(0, 65535);
    m_robotStartAddr->setValue(0);
    m_robotStartAddr->setStyleSheet(Theme::spinBoxStyle());
    addrRow->addWidget(m_robotStartAddr);
    m_robotUnitId = new QSpinBox(m_modbusFieldsWidget);
    m_robotUnitId->setRange(1, 255);
    m_robotUnitId->setValue(1);
    m_robotUnitId->setStyleSheet(Theme::spinBoxStyle());
    addrRow->addWidget(m_robotUnitId);
    addrRow->addStretch();
    modbusLayout->addRow(QStringLiteral("起始寄存器 / 站号"), addrRow);

    form->addRow(QString(), m_modbusFieldsWidget);

    // Auto-read on capture (kept here in the tools panel, not on the main UI)
    m_robotAutoReadCheck = new QCheckBox(
        QStringLiteral("拍照时自动读取机器人位姿"), group);
    m_robotAutoReadCheck->setChecked(false);
    form->addRow(QString(), m_robotAutoReadCheck);

    // Action buttons
    auto* btnRow = new QHBoxLayout();
    btnRow->setSpacing(8);
    m_btnRobotConnect = new QPushButton(QStringLiteral("连接"), group);
    m_btnRobotConnect->setStyleSheet(Theme::primaryButtonStyle());
    btnRow->addWidget(m_btnRobotConnect);
    m_btnRobotSimulate = new QPushButton(QStringLiteral("模拟连接成功"), group);
    m_btnRobotSimulate->setStyleSheet(Theme::secondaryButtonStyle());
    btnRow->addWidget(m_btnRobotSimulate);
    btnRow->addStretch();
    form->addRow(QString(), btnRow);

    auto* hint = new QLabel(group);
    hint->setWordWrap(true);
    hint->setStyleSheet(QStringLiteral(
        "color: %1; font-size: %2px;")
        .arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));
    hint->setText(QStringLiteral(
        "连接成功后，主界面会显示「拍照位姿」与「戳点位姿」按钮。"
        "UR Realtime 协议下机器人主动推流，读取到的姿态分量为轴角(弧度)而非欧拉角度数。"
        "UR RTDE (30004) 是 UR 推荐的新接口（30003 已废弃），同样返回轴角(弧度)，"
        "但字段按名称索取，不存在偏移错位问题；机器人同时只允许一个 RTDE 客户端。"
        "博纳斯(纳博特) JSON/TCP 协议读取当前 TCP 位姿（x y z rx ry rz，mm/度），"
        "应答字段名未知时会自动尝试常见字段并把原始应答写进运行日志。"
        "埃夫特走 EfortSDK，IP 必填、端口不填：厂商 SDK 的端口在库里写死 8100"
        "（厂商手册把 8000/8100 这段留作示教器/SDK 内部服务），本页端口输入框在该协议下隐藏；"
        "客户自己开的用户 socket（例如 8003）不用于这条链路。"
        "若把「IP:端口」整串粘进来，程序会只取 IP 并把端口部分标注出来"
        "（整串交给 SDK 会被它解析成另一个 IP，且不报错）。"
        "读取基坐标下的 TCP 位姿。"
        "无真机时可点击「模拟连接成功」验证按钮显示与样式。"));
    form->addRow(QString(), hint);

    pageLayout->addWidget(group);
    pageLayout->addStretch();
    stack->addWidget(wrapScrollable(page, stack));

    auto updateProtocolFields = [this](int index) {
        const bool isModbus = (index == 0);
        m_modbusFieldsWidget->setVisible(isModbus);
        // 埃夫特（index 3）走 EfortSDK：地址串由 SDK 决定，端口不参与，
        // 所以把端口框收起来（留空），避免给用户一个"填了就有用"的错觉。
        m_robotPort->setVisible(index != 3);
        // Default ports: Modbus TCP 502, UR realtime 30003, 博纳斯/纳博特 6001,
        // UR RTDE 30004.
        m_robotPort->setValue(index == 1 ? 30003
                             : index == 2 ? 6001
                             : index == 4 ? 30004
                                          : 502);
        // 端口提示只对埃夫特有意义，切走协议就撤掉（IP 框里的文字不动）。
        if (m_robotHostNote) {
            m_robotHostNote->clear();
            m_robotHostNote->setVisible(false);
        }
    };
    connect(m_robotProtocol, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, updateProtocolFields);
    updateProtocolFields(0);

    connect(m_btnRobotConnect, &QPushButton::clicked, this, [this]() {
        if (m_btnRobotConnect->text() == QStringLiteral("连接")) {
            const int protocol = m_robotProtocol->currentIndex();
            bool okScale = false;
            const double scale = m_robotScale->text().trimmed().toDouble(&okScale);
            if (protocol == 0 && !okScale) {
                setRobotStatus(QStringLiteral("系数格式无效"), true);
                return;
            }
            // 埃夫特（protocol 3）不走 TCP 端口：传 0，由适配器把 IP 交给 SDK。
            const quint16 port = (protocol == 3)
                ? 0
                : static_cast<quint16>(m_robotPort->value());
            QString host = m_robotHost->text().trimmed();
            if (protocol == 3) {
                // 埃夫特 SDK 只收 IP（控制器一侧固定 8100，见 EfortPoseReader.h）。
                // 客户给的 "192.168.0.1:8003" 整串直接喂进去，SDK 会解析成
                // 192.171.44.131 而不报错 —— 就地截断、写回输入框，并说清为什么。
                const EfortPoseReader::AddressSplit split =
                    EfortPoseReader::splitAddress(host);
                host = split.ip;
                if (split.portSuffix.isEmpty()) {
                    m_robotHostNote->clear();
                    m_robotHostNote->setVisible(false);
                } else {
                    m_robotHost->setText(split.ip);
                    m_robotHostNote->setText(QStringLiteral(
                        "已忽略输入里的“:%1”：埃夫特端口由 SDK 固定（控制器内部服务 8100），"
                        "只填 IP 即可，本连接不使用客户自定义的 socket 端口。")
                        .arg(split.portSuffix));
                    m_robotHostNote->setVisible(true);
                }
            }
            emit robotConnectRequested(
                host,
                port,
                protocol,
                m_robotFormat->currentIndex(), scale,
                static_cast<quint8>(m_robotUnitId->value()),
                static_cast<quint16>(m_robotStartAddr->value()));
        } else {
            emit robotDisconnectRequested();
        }
    });
    connect(m_btnRobotSimulate, &QPushButton::clicked, this,
            [this]() { emit robotSimulateConnectRequested(); });
    connect(m_robotAutoReadCheck, &QCheckBox::toggled, this,
            [this](bool on) { emit robotAutoReadToggled(on); });
}

void ToolsPanel::setRobotAutoRead(bool on)
{
    if (!m_robotAutoReadCheck || m_robotAutoReadCheck->isChecked() == on)
        return;
    // Keep the panel's checkbox and AppConfig "auto_read_robot_pose" one single
    // state: the settings dialog and this checkbox are views of the same key.
    const QSignalBlocker block(m_robotAutoReadCheck);
    m_robotAutoReadCheck->setChecked(on);
}

void ToolsPanel::setRobotStatus(const QString& text, bool ok)
{
    if (!m_robotStatus)
        return;
    m_robotStatus->setText(text);
    m_robotStatus->setStyleSheet(QStringLiteral(
        "font-size: %1px; color: %2;")
        .arg(Theme::FONT_HINT)
        .arg(ok ? Theme::ERROR : Theme::TEXT_HINT));
}

void ToolsPanel::setRobotConnected(bool connected)
{
    if (!m_btnRobotConnect)
        return;
    m_btnRobotConnect->setText(connected ? QStringLiteral("断开")
                                         : QStringLiteral("连接"));
}

// ══════════════════════════════════════════════════════════════════════
// Measurement tools — parity with the Python 3D 测量一体化工具
//
// 第 7 回合 P3：每个测量方法都是左侧列表里的一个独立工具项，各占一个
// MeasurePage（共用基类：ROI 取点与需求提示、结果表、重复性序列、快照发布）。
// 面板本身只保留三样**跨页共享**的状态：
//   * 最近一帧点云（引用计数，不拷贝）；
//   * ROI 矩形（图像像素）——按当前方法的 ROI 需求落到 A / B，
//     并用 MeasureTools::planRoiDrag 决定"替换 / 提示 / 从 A 重来"；
//   * 重复性序列库（跨方法、跨帧累积，仅内存，不落盘）。
// 结果与显示载荷都在各页内部，所以"这一页测的是什么"不会串到别的页。
// ══════════════════════════════════════════════════════════════════════

void ToolsPanel::buildMeasurePages(QStackedWidget* stack)
{
    int n = 0;
    const MeasureTools::MethodSpec* specs = MeasureTools::methodSpecs(n);
    m_firstMeasureRow = m_toolList->count();
    for (int i = 0; i < n; ++i) {
        // 左侧列表项与页面一一对应（顺序 = methodSpecs()）。
        m_toolList->addItem(QString::fromUtf8(specs[i].name));
        MeasurePage* page = MeasurePages::create(specs[i].method, stack);
        page->setObjectName(QStringLiteral("measure_page_%1")
                                .arg(QString::fromUtf8(specs[i].id)));
        page->setSeriesStore(&m_series);
        stack->addWidget(wrapScrollable(page, stack));
        m_pages.push_back(page);

        connect(page, &MeasurePage::snapshotReady,
                this, &ToolsPanel::measurementUpdated);
        connect(page, &MeasurePage::clearRoiRequested,
                this, &ToolsPanel::clearMeasurementRois);
        connect(page, &MeasurePage::logRequested, this,
                [this](const QString& line) { emit logMessage(line); });
        // 8 个页的「3D 偏差着色」勾选状态必须一致：一页改了，其余 7 页跟着改，
        // 再把事件转给 3D 工具栏的孪生按钮（MainWindow 是唯一的同步者）。
        connect(page, &MeasurePage::deviationColoringChanged, this,
                [this, page](bool on) {
                    for (MeasurePage* other : m_pages) {
                        if (other != page)
                            other->setDeviationColoring(on);
                    }
                    emit deviationColoringChanged(on);
                });
    }
}

bool ToolsPanel::activeToolIsMeasure() const
{
    const int row = m_toolList ? m_toolList->currentRow() : -1;
    const int idx = row - m_firstMeasureRow;
    return idx >= 0 && idx < static_cast<int>(m_pages.size());
}

void ToolsPanel::onToolChanged(int row)
{
    // 换页先重算冻结：切走「像素→3D」立刻解冻，切回来（离线+图像有效）重新冻结。
    // （列表项 → 堆叠页的 setCurrentIndex 在 buildUi() 里先于本槽连接，所以这里
    //   m_stack->currentWidget() 已经是新页。）
    updateOfflineFreeze();
    const int idx = row - m_firstMeasureRow;
    if (idx < 0 || idx >= static_cast<int>(m_pages.size())) {
        // 非测量工具：保留 m_page（它仍是"最近测过的那一页"，2D/3D 显示页
        // 要接着显示它的结果），只是不再接收 ROI。
        m_measureActive = false;
        return;
    }
    MeasurePage* page = m_pages[static_cast<std::size_t>(idx)];
    m_measureActive = true;
    if (page == m_page) {
        pushRoiToActivePage(
            QString::fromStdString(MeasureTools::roiStateText(page->roiCount(),
                                                              m_roiRects.size())));
        return;
    }
    m_page = page;
    pushRoiToActivePage(
        QString::fromStdString(MeasureTools::roiStateText(page->roiCount(),
                                                          m_roiRects.size())));
    page->refreshSeriesUi();
    // P4：选中方法时写一条 [测量-说明]。
    emit logMessage(page->explainLine());
}

void ToolsPanel::pushRoiToActivePage(const QString& note)
{
    if (!m_page)
        return;
    // 页里自带取点（roiImageToGrid + pointsInRoiIndexed），并把 ROI 需求、
    // 当前选择与这次拖框的结论一起显示出来。
    m_page->setRoiRects(m_roiRects, note);
}

void ToolsPanel::setMeasurementCloud(const FrameBuffer::DoubleBuf& grid, int gridW,
                                     int gridH, int imageW, int imageH)
{
    m_measureGrid = grid;                 // refcount bump, no copy
    m_measureGridW = gridW;
    m_measureGridH = gridH;
    m_imageW = imageW;
    m_imageH = imageH;

    QString text = QStringLiteral("尚未采集（先在主窗口点击「拍照」）");
    if (gridW > 0) {
        int valid = 0;
        if (grid && gridH > 0) {
            const std::vector<double>& g = *grid;
            const std::size_t cells = static_cast<std::size_t>(gridW) * gridH;
            for (std::size_t i = 0; i < cells && i * 3 + 2 < g.size(); ++i) {
                const double x = g[i * 3], y = g[i * 3 + 1], z = g[i * 3 + 2];
                if (std::isfinite(x) && std::isfinite(y) && std::isfinite(z)
                    && !(x == 0.0 && y == 0.0 && z == 0.0)) {
                    ++valid;
                }
            }
        }
        text = QStringLiteral("%1 × %2 网格，%3 个有效点").arg(gridW).arg(gridH).arg(valid);
    }

    // A new capture invalidates the previous ROI selection: the rectangles are
    // in image pixels and the new frame may have a different size.
    if (m_imageW > 0 && m_imageH > 0 && !m_roiRects.isEmpty()) {
        m_roiRects.clear();
        emit roisChanged({}, {});
    }

    // 一帧点云作废所有页的结果（重复性序列刻意保留：跨帧累积正是它的用途）。
    for (MeasurePage* page : m_pages) {
        page->setCloud(m_measureGrid, gridW, gridH, imageW, imageH, text);
        page->resetResult();
    }
    if (m_page) {
        pushRoiToActivePage(
            QString::fromStdString(MeasureTools::roiStateText(m_page->roiCount(),
                                                              m_roiRects.size())));
        emit measurementUpdated(m_page->snapshot());
    }
}

void ToolsPanel::setMeasurementImage(const QImage& image)
{
    m_measureImage = image;               // QImage is implicitly shared: no pixel copy
    for (MeasurePage* page : m_pages)
        page->setImage(m_measureImage);
}

void ToolsPanel::onRoiSelected(const QRect& rect)
{
    if (rect.width() < 4 || rect.height() < 4)
        return;
    if (!m_measureActive || !m_page) {
        // 当前列表项不是测量方法：ROI 没有归属，直接忽略。
        // （每个测量方法都是独立工具项，选好方法再框才是它的 ROI。）
        return;
    }
    if (!m_measureGrid || m_imageW <= 0) {
        pushRoiToActivePage(QStringLiteral("尚未采集点云：请先在主窗口点击「拍照」。"));
        return;
    }
    // P3.2：第 3 次拖框不再"悄悄覆盖重来"——策略与提示语都来自方法自己的
    // ROI 需求（MeasureTools::planRoiDrag，纯逻辑，tests 里有断言）。
    const MeasureTools::RoiDragPlan plan =
        MeasureTools::planRoiDrag(m_page->roiCount(), m_roiRects.size());
    if (plan.slot < 0) {
        // 本方法不用 ROI：这次拖框被忽略，必须保留动作说明（为什么没生效）。
        pushRoiToActivePage(QString::fromStdString(plan.note));
        return;
    }
    if (plan.clearAll)
        m_roiRects.clear();
    m_roiRects.push_back(rect);
    emit roisChanged(m_roiRects, roiLabels());
    // W1：框落定之后要讲"现在的状态"。以前这里显示的是 plan.note——那句话是按
    // **拖框之前**的框数写的，所以双 ROI 方法拖完第 2 个框还在说"当前 1/2，
    // 再拖一次框 ROI B"（第 1 个框落下后更会停在"当前 0/2"）。清空重来/被忽略
    // 两类动作提示由 roiNoteAfterDrag() 原样保留。
    pushRoiToActivePage(QString::fromStdString(
        MeasureTools::roiNoteAfterDrag(m_page->roiCount(), plan, m_roiRects.size())));
}

void ToolsPanel::clearMeasurementRois()
{
    m_roiRects.clear();
    emit roisChanged({}, {});
    if (m_page) {
        pushRoiToActivePage(
            QString::fromStdString(MeasureTools::roiStateText(m_page->roiCount(), 0)));
    }
}

QStringList ToolsPanel::roiLabels() const
{
    QStringList labels;
    for (int i = 0; i < m_roiRects.size(); ++i)
        labels << QStringLiteral("ROI %1").arg(QChar(QLatin1Char('A').unicode() + i));
    return labels;
}

void ToolsPanel::setDeviationColoring(bool on)
{
    // 只同步勾选状态（8 个页保持一致），重算交给最近测量的那一页自己做，
    // 免得一次点击触发 8 次 3D 点云重传。
    for (MeasurePage* page : m_pages)
        page->setDeviationColoring(on);
    if (m_page)
        m_page->rerun();
}
