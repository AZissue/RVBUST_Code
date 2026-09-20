#include "ui/ToolsPanel.h"

#include "logic/GeometryTools.h"
#include "logic/CalibrationService.h"
#include "logic/PixelTo3DTools.h"
#include "logic/PlyPointReader.h"
#include "logic/ToolInputParser.h"
#include "logic/TransformTools.h"
#include "ui/Image2DView.h"
#include "ui/Theme.h"

#include <QApplication>
#include <QClipboard>
#include <QCheckBox>
#include <QDir>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QHeaderView>   // QTableWidget's header API (incomplete type in QtWidgets)
#include <QImage>
#include <QLabel>
#include <QLineEdit>
#include <QPainter>
#include <QPaintEvent>
#include <QPolygon>
#include <QTextEdit>
#include <QVBoxLayout>
#include <QtConcurrent>
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <vector>

namespace {

QLineEdit* makeTextInput(QWidget* parent)
{
    auto* edit = new QLineEdit(parent);
    edit->setStyleSheet(Theme::inputStyle());
    return edit;
}

// The global combo-box QSS strips the native drop-down arrow; repaint a small
// down arrow at the right edge so the drop-down affordance stays visible.
class ArrowComboBox : public QComboBox {
public:
    explicit ArrowComboBox(QWidget* parent = nullptr) : QComboBox(parent) {}

protected:
    void paintEvent(QPaintEvent* event) override
    {
        QComboBox::paintEvent(event);
        QPainter p(this);
        p.setRenderHint(QPainter::Antialiasing);
        const QRect r = rect();
        const int x = r.right() - 18;
        const int cy = r.center().y();
        QPolygon tri;
        tri << QPoint(x, cy - 3) << QPoint(x + 9, cy - 3) << QPoint(x + 4, cy + 4);
        p.setPen(Qt::NoPen);
        p.setBrush(QColor(Theme::TEXT_HINT));
        p.drawPolygon(tri);
    }
};

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
    setMinimumSize(720, 520);
    setAttribute(Qt::WA_DeleteOnClose, false);
    buildUi();
}

void ToolsPanel::buildUi()
{
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(16, 16, 16, 16);
    layout->setSpacing(16);

    m_toolList = new QListWidget(this);
    m_toolList->setFixedWidth(140);
    m_toolList->addItem(QStringLiteral("欧氏距离"));
    m_toolList->addItem(QStringLiteral("像素→3D"));
    m_toolList->addItem(QStringLiteral("手眼标定"));
    m_toolList->addItem(QStringLiteral("坐标转换"));
    m_toolList->addItem(QStringLiteral("机器人通信"));
    m_toolList->addItem(QStringLiteral("测量"));
    m_toolList->setStyleSheet(QStringLiteral(
        "QListWidget { background: %1; border: 1px solid %2; border-radius: %3px;"
        " font-size: %4px; }"
        "QListWidget::item { padding: 8px 10px; }"
        "QListWidget::item:selected { background: rgba(22,119,255,0.12); color: %5; }")
        .arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS)
        .arg(Theme::FONT_BODY).arg(Theme::PRIMARY));
    layout->addWidget(m_toolList);

    m_stack = new QStackedWidget(this);
    buildDistancePage(m_stack);
    buildPixelTo3DPage(m_stack);
    buildCalibrationPage(m_stack);
    buildTransformPage(m_stack);
    buildRobotCommPage(m_stack);
    buildMeasurePage(m_stack);
    layout->addWidget(m_stack, 1);

    connect(m_toolList, &QListWidget::currentRowChanged,
            m_stack, &QStackedWidget::setCurrentIndex);
    m_toolList->setCurrentRow(0);

    m_calibWatcher = new QFutureWatcher<CalibrationService::Result>(this);
    connect(m_calibWatcher,
            &QFutureWatcher<CalibrationService::Result>::finished,
            this, &ToolsPanel::onCalibrationFinished);
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
    stack->addWidget(page);

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

    // Data folder
    auto* dirRow = new QHBoxLayout();
    dirRow->setSpacing(8);
    m_p2dDir = makeTextInput(group);
    m_p2dDir->setObjectName(QStringLiteral("p2d_dir"));
    m_p2dDir->setPlaceholderText(QStringLiteral("选择含 png + ply 的会话文件夹"));
    dirRow->addWidget(m_p2dDir, 1);
    auto* browseBtn = new QPushButton(QStringLiteral("浏览"), group);
    browseBtn->setStyleSheet(Theme::secondaryButtonStyle());
    dirRow->addWidget(browseBtn);
    form->addRow(QStringLiteral("数据文件夹"), dirRow);

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
        "x, y（像素坐标，也可在下方图像上点击取点）"));
    form->addRow(QStringLiteral("像素坐标"), m_p2dPixel);

    // Embedded 2D image view (click to pick pixel)
    m_p2dView = new Image2DView(group);
    m_p2dView->setMinimumHeight(240);
    m_p2dView->setStyleSheet(QStringLiteral(
        "border: 1px solid %1; border-radius: 4px;")
        .arg(Theme::BORDER_DEFAULT));
    form->addRow(QString(), m_p2dView);

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
    stack->addWidget(page);

    connect(browseBtn, &QPushButton::clicked, this, [this]() {
        const QString dir = QFileDialog::getExistingDirectory(
            this, QStringLiteral("选择数据文件夹"), m_p2dDir->text().trimmed());
        if (dir.isEmpty())
            return;
        m_p2dDir->setText(dir);
        refreshPixelTo3DImages();
    });
    connect(m_p2dImageCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int index) { showPixelTo3DImage(index); });
    connect(m_p2dView, &Image2DView::pixelClicked, this, [this](int x, int y) {
        m_p2dPixel->setText(QStringLiteral("%1, %2").arg(x).arg(y));
        m_p2dHint->clear();
    });
    connect(calcBtn, &QPushButton::clicked,
            this, &ToolsPanel::updatePixelTo3DResult);
    connect(m_p2dCopyBtn, &QPushButton::clicked, this, [this]() {
        if (!m_p2dResultValue.isEmpty())
            QApplication::clipboard()->setText(m_p2dResultValue);
    });
    for (QLineEdit* edit : { m_p2dDir, m_p2dIntrinsic, m_p2dExtrinsic, m_p2dPixel })
        connect(edit, &QLineEdit::textChanged, this, [this](const QString&) {
            m_p2dHint->clear();
        });
}

void ToolsPanel::refreshPixelTo3DImages()
{
    const QString dir = m_p2dDir->text().trimmed();
    m_p2dImageCombo->clear();
    if (dir.isEmpty())
        return;
    QDir qdir(dir);
    const QStringList pngs = qdir.entryList(
        { QStringLiteral("*.png"), QStringLiteral("*.jpg"), QStringLiteral("*.bmp") },
        QDir::Files, QDir::Name);
    for (const QString& name : pngs)
        m_p2dImageCombo->addItem(name);
    if (m_p2dImageCombo->count() > 0)
        showPixelTo3DImage(0);
}

void ToolsPanel::showPixelTo3DImage(int index)
{
    const QString dir = m_p2dDir->text().trimmed();
    if (dir.isEmpty() || index < 0 || index >= m_p2dImageCombo->count())
        return;
    const QString path = dir + QLatin1Char('/') + m_p2dImageCombo->itemText(index);
    QImage img(path);
    if (!img.isNull())
        m_p2dView->updateFrame(img);
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

    std::array<double, 3> pt{};
    bool ok = false;
    // Aligned data: point count == image size -> direct pixel index lookup.
    if (ply.xyz.size() == static_cast<std::size_t>(w) * h * 3) {
        std::size_t idx = 0;
        if (PixelTo3DTools::alignedIndex(px, py, w, h, idx))
            ok = PixelTo3DTools::pointAt(ply.xyz, idx, pt);
    } else {
        // Non-aligned (e.g. SwingLineScan + correspond2d=false): project the
        // point cloud through camera intrinsics (+ optional extrinsics).
        ToolInputParser::ParseResult k = ToolInputParser::parseNumberList(
            m_p2dIntrinsic->text().toStdString(), 9);
        if (k.status != ToolInputParser::ParseStatus::Ok) {
            fail(QStringLiteral("点云与图像尺寸不一致，需要相机内参：%1")
                     .arg(parseErrorText(k, 9)));
            return;
        }
        PixelTo3DTools::Intrinsics intr{
            k.values[0], k.values[4], k.values[2], k.values[5]
        };
        if (intr.fx <= 0.0 || intr.fy <= 0.0) {
            fail(QStringLiteral("内参无效（fx/fy 必须大于 0）"));
            return;
        }
        std::array<double, 16> ext{};
        const double* extPtr = nullptr;
        if (!m_p2dExtrinsic->text().trimmed().isEmpty()) {
            ToolInputParser::ParseResult e = ToolInputParser::parseNumberList(
                m_p2dExtrinsic->text().toStdString(), 16);
            if (e.status != ToolInputParser::ParseStatus::Ok) {
                fail(QStringLiteral("相机外参：%1").arg(parseErrorText(e, 16)));
                return;
            }
            for (int i = 0; i < 16; ++i)
                ext[static_cast<std::size_t>(i)] = e.values[i];
            extPtr = ext.data();
        }
        std::vector<int> index;
        PixelTo3DTools::buildProjectedIndex(
            ply.xyz, extPtr, intr, w, h, index);
        ok = PixelTo3DTools::queryIndex(
            index, w, h, px, py, ply.xyz, pt);
    }

    if (!ok) {
        fail(QStringLiteral("该像素无有效 3D 点（背景或无效深度）"));
        return;
    }

    m_p2dResultValue = QStringLiteral("%1, %2, %3")
        .arg(pt[0], 0, 'f', 3).arg(pt[1], 0, 'f', 3).arg(pt[2], 0, 'f', 3);
    m_p2dResult->setText(m_p2dResultValue);
}

void ToolsPanel::buildCalibrationPage(QStackedWidget* stack)
{
    auto* page = new QWidget(stack);
    auto* pageLayout = new QVBoxLayout(page);

    auto* group = new QGroupBox(QStringLiteral("手眼标定（离线计算）"), page);
    auto* form = new QFormLayout(group);
    form->setFieldGrowthPolicy(QFormLayout::AllNonFixedFieldsGrow);

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

    m_calibPoseFile = makeTextInput(group);
    m_calibPoseFile->setObjectName(QStringLiteral("calib_pose_file"));
    m_calibPoseFile->setText(QStringLiteral("pose.txt"));
    form->addRow(QStringLiteral("位姿文件"), m_calibPoseFile);

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
    stack->addWidget(page);

    connect(browseBtn, &QPushButton::clicked, this, [this]() {
        const QString dir = QFileDialog::getExistingDirectory(
            this, QStringLiteral("选择数据文件夹"), m_calibDir->text().trimmed());
        if (!dir.isEmpty())
            m_calibDir->setText(dir);
    });
    connect(m_calibCalcBtn, &QPushButton::clicked,
            this, &ToolsPanel::updateCalibrationResult);
    connect(m_calibCopyBtn, &QPushButton::clicked, this, [this]() {
        if (!m_calibResult->toPlainText().isEmpty())
            QApplication::clipboard()->setText(m_calibResult->toPlainText());
    });
    for (QLineEdit* edit : { m_calibDir, m_calibPoseFile })
        connect(edit, &QLineEdit::textChanged, this, [this](const QString&) {
            m_calibHint->clear();
        });
}

void ToolsPanel::updateCalibrationResult()
{
    if (m_calibWatcher->isRunning())
        return;
    m_calibHint->clear();
    auto fail = [this](const QString& message) {
        m_calibHint->setText(message);
    };

    const QString dir = m_calibDir->text().trimmed();
    if (dir.isEmpty()) {
        fail(QStringLiteral("请先选择数据文件夹"));
        return;
    }
    const QString poseName = m_calibPoseFile->text().trimmed();
    if (poseName.isEmpty()) {
        fail(QStringLiteral("位姿文件名不能为空"));
        return;
    }
    const QString posePath = dir + QLatin1Char('/') + poseName;
    QFile poseFile(posePath);
    if (!poseFile.open(QIODevice::ReadOnly | QIODevice::Text)) {
        fail(QStringLiteral("无法读取位姿文件: %1").arg(poseName));
        return;
    }
    std::vector<QString> poseLines;
    QTextStream ts(&poseFile);
    ts.setCodec("UTF-8");
    while (!ts.atEnd()) {
        const QString line = ts.readLine().trimmed();
        if (!line.isEmpty())
            poseLines.push_back(line);
    }
    if (poseLines.empty()) {
        fail(QStringLiteral("位姿文件为空"));
        return;
    }

    CalibrationService::Params params;
    params.eyeInHand = m_calibEyeCombo->currentIndex() == 1;
    params.markerType = m_calibMarkerCombo->currentIndex() == 0 ? 1 : 0;
    params.isPoseMm = m_calibPoseUnitCombo->currentIndex() == 0;
    params.isPoseDegree = m_calibAngleUnitCombo->currentIndex() == 0;
    params.autoRemoveLargeError = m_calibAutoRemove->isChecked();

    m_calibCalcBtn->setEnabled(false);
    m_calibCalcBtn->setText(QStringLiteral("计算中..."));
    m_calibWatcher->setFuture(QtConcurrent::run([dir, poseLines, params]() {
        return CalibrationService::calibrateMarker(dir, poseLines, params);
    }));
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

    QString text = QStringLiteral("标定成功（使用 %1 组数据）\n"
                                  "总平均误差: %2 mm\n\n"
                                  "4×4 矩阵（行主序）:\n")
        .arg(r.usedCount).arg(r.totalMeanError, 0, 'f', 3);
    for (int row = 0; row < 4; ++row) {
        QStringList vals;
        for (int col = 0; col < 4; ++col)
            vals << QString::number(
                r.matrix[static_cast<std::size_t>(row * 4 + col)], 'f', 6);
        text += vals.join(QStringLiteral("  ")) + QLatin1Char('\n');
    }
    text += QStringLiteral("\n逐组误差:\n");
    const std::size_t n = r.errors.size();
    for (std::size_t i = 0; i < n; ++i) {
        const bool failed2d = static_cast<std::size_t>(r.success2D.size()) > i
            && r.success2D[i] != 1;
        const bool failed3d = static_cast<std::size_t>(r.success3D.size()) > i
            && r.success3D[i] != 1;
        text += QStringLiteral("  第 %1 组: %2 mm%3\n")
            .arg(i + 1).arg(r.errors[i], 0, 'f', 3)
            .arg((failed2d || failed3d) ? QStringLiteral("（识别失败）") : QString());
    }
    m_calibResult->setPlainText(text);
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
    m_poseFormatCombo->addItem(QStringLiteral("欧拉角 RPY（Static XYZ，Yaskawa 安川）"));
    m_poseFormatCombo->addItem(QStringLiteral("欧拉角 WPR（FANUC / KUKA ABC）"));
    m_poseFormatCombo->addItem(QStringLiteral("欧拉角 ZYX 内旋（Rx·Ry·Rz）"));
    m_poseFormatCombo->addItem(QStringLiteral("四元数（w x y z，ABB / HandEyeSDK 1）"));
    m_poseFormatCombo->addItem(QStringLiteral("四元数（x y z w，ROS / HandEyeSDK 2）"));
    m_poseFormatCombo->addItem(QStringLiteral("旋转矩阵（3×3，行主序）"));
    m_poseFormatCombo->addItem(QStringLiteral("旋转矢量（轴角，UR 优傲）"));
    m_poseFormatCombo->setStyleSheet(Theme::comboBoxStyle());
    poseForm->addRow(QStringLiteral("姿态格式"), m_poseFormatCombo);

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
    stack->addWidget(page);

    connect(m_mountCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int index) {
                m_poseGroup->setEnabled(index == 1);
            });
    connect(m_poseFormatCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int) { updatePoseInputHint(); });
    connect(m_angleUnitCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int) { updatePoseInputHint(); });
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
    const auto fmt = static_cast<TransformTools::RotationFormat>(
        m_poseFormatCombo->currentIndex());
    const QString unit = m_angleUnitCombo->currentIndex() == 0
                             ? QStringLiteral("度")
                             : QStringLiteral("弧度");

    QString placeholder;
    QString desc;
    switch (fmt) {
    case TransformTools::RotationFormat::EulerRpy:
        placeholder = QStringLiteral("px, py, pz, rx, ry, rz（欧拉角 RPY，%1）").arg(unit);
        desc = QStringLiteral(
            "Static XYZ / RPY（外旋）：R = Rz·Ry·Rx，按 (rx, ry, rz) = (X, Y, Z) 直填；"
            "Yaskawa 安川 RX/RY/RZ、珞石（官方 SDK 标 XYZ 欧拉角，单位弧度）、"
            "FANUC 标准手册（W绕X、P绕Y、R绕Z）均按此直填");
        break;
    case TransformTools::RotationFormat::EulerWpr:
        placeholder = QStringLiteral("px, py, pz, w, p, r（FANUC WPR，%1）").arg(unit);
        desc = QStringLiteral(
            "按 (W, P, R) 直填：R = Rz(W)·Ry(P)·Rx(R)，即角度顺序 = 绕 Z、Y、X；"
            "KUKA ABC 同此顺序；RVC 官方软件导出的 FANUC 位姿文件实测适用");
        break;
    case TransformTools::RotationFormat::EulerZyxIntrinsic:
        placeholder = QStringLiteral("px, py, pz, rx, ry, rz（欧拉角 ZYX 内旋，%1）").arg(unit);
        desc = QStringLiteral(
            "ZYX 内旋：R = Rx·Ry·Rz，按 (rx, ry, rz) = (X, Y, Z) 输入；"
            "与 Static XYZ（Rz·Ry·Rx）一般不相等");
        break;
    case TransformTools::RotationFormat::QuatWxyz:
        placeholder = QStringLiteral("px, py, pz, w, x, y, z（四元数 w x y z）");
        desc = QStringLiteral(
            "四元数顺序 w x y z（标量在前）；ABB（RAPID Q1..Q4）、"
            "RVC HandEyeSDK poseType=1");
        break;
    case TransformTools::RotationFormat::QuatXyzw:
        placeholder = QStringLiteral("px, py, pz, x, y, z, w（四元数 x y z w）");
        desc = QStringLiteral(
            "四元数顺序 x y z w（标量在后）；ROS、RVC HandEyeSDK poseType=2");
        break;
    case TransformTools::RotationFormat::RotationMatrix9:
        placeholder = QStringLiteral("px, py, pz, 旋转矩阵 9 个值（行主序）");
        desc = QStringLiteral("3×3 旋转矩阵，行主序 9 个值");
        break;
    case TransformTools::RotationFormat::RotationVector:
        placeholder = QStringLiteral("px, py, pz, rx, ry, rz（旋转矢量，%1）").arg(unit);
        desc = QStringLiteral(
            "旋转矢量（轴角）：方向 = 转轴，长度 = 转角；UR 优傲，长度单位随角度单位");
        break;
    }
    m_poseInput->setPlaceholderText(placeholder);
    m_rotDescLabel->setText(desc);
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
        const auto fmt = static_cast<TransformTools::RotationFormat>(
            m_poseFormatCombo->currentIndex());
        const auto unit = m_angleUnitCombo->currentIndex() == 0
                              ? TransformTools::AngleUnit::Degree
                              : TransformTools::AngleUnit::Radian;
        const size_t poseCount = 3 + static_cast<size_t>(
            TransformTools::rotationValueCount(fmt));
        ToolInputParser::ParseResult pose = ToolInputParser::parseNumberList(
            m_poseInput->text().toStdString(), poseCount);
        if (pose.status != ToolInputParser::ParseStatus::Ok) {
            fail(QStringLiteral("机械臂位姿：%1").arg(parseErrorText(pose, poseCount)));
            return;
        }

        const auto poseUnit = m_poseUnitCombo->currentIndex() == 0
                                  ? TransformTools::LengthUnit::Millimeter
                                  : TransformTools::LengthUnit::Meter;
        const double px = TransformTools::toMillimeters(pose.values[0], poseUnit);
        const double py = TransformTools::toMillimeters(pose.values[1], poseUnit);
        const double pz = TransformTools::toMillimeters(pose.values[2], poseUnit);
        std::vector<double> rotVals(pose.values.begin() + 3, pose.values.end());
        const TransformTools::Mat4 baseToTcp = TransformTools::poseToMat4(
            px, py, pz, fmt, unit, rotVals);
        TransformTools::eyeInHandPoint(camMat, baseToTcp, cx, cy, cz, bx, by, bz);
    }

    m_transformHint->clear();
    m_transformValues = QStringLiteral("%1, %2, %3")
        .arg(bx, 0, 'f', 3).arg(by, 0, 'f', 3).arg(bz, 0, 'f', 3);
    m_transformResult->setText(m_transformValues);
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
        "博纳斯(纳博特) JSON/TCP 协议读取当前 TCP 位姿（x y z rx ry rz，mm/度），"
        "应答字段名未知时会自动尝试常见字段并把原始应答写进运行日志。"
        "无真机时可点击「模拟连接成功」验证按钮显示与样式。"));
    form->addRow(QString(), hint);

    pageLayout->addWidget(group);
    pageLayout->addStretch();
    stack->addWidget(page);

    auto updateProtocolFields = [this](int index) {
        const bool isModbus = (index == 0);
        m_modbusFieldsWidget->setVisible(isModbus);
        // Default ports: Modbus TCP 502, UR realtime 30003, 博纳斯/纳博特 6001.
        m_robotPort->setValue(index == 1 ? 30003 : (index == 2 ? 6001 : 502));
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
            emit robotConnectRequested(
                m_robotHost->text().trimmed(),
                static_cast<quint16>(m_robotPort->value()),
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
// Measurement tool — parity with the Python 3D 测量一体化工具
// ══════════════════════════════════════════════════════════════════════

namespace {

// Coarse quality label for the result table (可信度).  Point count dominates;
// the RMS test only applies to methods where a residual is meaningful (-1
// means "not applicable").
QString confidenceFor(int points, double rms)
{
    if (points >= 2000 && (rms < 0.0 || rms <= 0.05))
        return QStringLiteral("高");
    if (points >= 300)
        return QStringLiteral("中");
    return QStringLiteral("低");
}

QString fmt4(double v)
{
    return QString::number(v, 'f', 4);
}

} // namespace

void ToolsPanel::buildMeasurePage(QStackedWidget* stack)
{
    auto* page = new QWidget(stack);
    auto* pageLayout = new QVBoxLayout(page);
    pageLayout->setSpacing(10);

    // ── data source ──
    auto* cloudGroup = new QGroupBox(QStringLiteral("数据源"), page);
    auto* cloudForm = new QFormLayout(cloudGroup);
    m_measureCloudLabel = new QLabel(QStringLiteral("尚未采集（先在主窗口点击「拍照」）"),
                                     cloudGroup);
    m_measureCloudLabel->setObjectName(QStringLiteral("measure_cloud_label"));
    m_measureCloudLabel->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                           .arg(Theme::TEXT_BODY).arg(Theme::FONT_HINT));
    cloudForm->addRow(QStringLiteral("当前点云"), m_measureCloudLabel);

    m_measureRoiLabel = new QLabel(QStringLiteral("未选择"), cloudGroup);
    m_measureRoiLabel->setObjectName(QStringLiteral("measure_roi_label"));
    m_measureRoiLabel->setWordWrap(true);
    m_measureRoiLabel->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                         .arg(Theme::TEXT_BODY).arg(Theme::FONT_HINT));
    cloudForm->addRow(QStringLiteral("测量区域"), m_measureRoiLabel);

    m_roiClearBtn = new QPushButton(QStringLiteral("清除区域"), cloudGroup);
    m_roiClearBtn->setStyleSheet(Theme::secondaryButtonStyle());
    cloudForm->addRow(QString(), m_roiClearBtn);
    pageLayout->addWidget(cloudGroup);

    // ── method + tolerances ──
    auto* methodGroup = new QGroupBox(QStringLiteral("测量方法"), page);
    auto* methodForm = new QFormLayout(methodGroup);

    m_measureMethod = new ArrowComboBox(methodGroup);
    m_measureMethod->setObjectName(QStringLiteral("measure_method"));
    m_measureMethod->setStyleSheet(Theme::comboBoxStyle());
    // Order and names follow the Python METHODS table (app.py) so the two tools
    // report the same quantities under the same names.
    m_measureMethod->addItem(QStringLiteral("平面度"));
    m_measureMethod->addItem(QStringLiteral("面到面高度(中位数)"));
    m_measureMethod->addItem(QStringLiteral("面面距离/夹角"));
    m_measureMethod->addItem(QStringLiteral("圆 / 孔径"));
    m_measureMethod->addItem(QStringLiteral("包围盒"));
    m_measureMethod->addItem(QStringLiteral("重复性统计"));
    methodForm->addRow(QStringLiteral("方法"), m_measureMethod);
    pageLayout->addWidget(methodGroup);

    auto* tolRow = new QHBoxLayout();
    m_tolEnable = new QCheckBox(QStringLiteral("启用公差"), methodGroup);
    m_tolEnable->setObjectName(QStringLiteral("measure_tol_enable"));
    m_tolEnable->setStyleSheet(QStringLiteral("font-size: %1px;").arg(Theme::FONT_HINT));
    tolRow->addWidget(m_tolEnable);
    auto* loLabel = new QLabel(QStringLiteral("下限"), methodGroup);
    loLabel->setStyleSheet(QStringLiteral("font-size: %1px;").arg(Theme::FONT_HINT));
    tolRow->addWidget(loLabel);
    m_tolLo = new QDoubleSpinBox(methodGroup);
    m_tolLo->setObjectName(QStringLiteral("measure_tol_lo"));
    m_tolLo->setDecimals(4);
    m_tolLo->setRange(-1.0e6, 1.0e6);
    m_tolLo->setValue(-0.05);
    m_tolLo->setStyleSheet(Theme::inputStyle());
    tolRow->addWidget(m_tolLo);
    auto* hiLabel = new QLabel(QStringLiteral("上限"), methodGroup);
    hiLabel->setStyleSheet(QStringLiteral("font-size: %1px;").arg(Theme::FONT_HINT));
    tolRow->addWidget(hiLabel);
    m_tolHi = new QDoubleSpinBox(methodGroup);
    m_tolHi->setObjectName(QStringLiteral("measure_tol_hi"));
    m_tolHi->setDecimals(4);
    m_tolHi->setRange(-1.0e6, 1.0e6);
    m_tolHi->setValue(0.05);
    m_tolHi->setStyleSheet(Theme::inputStyle());
    tolRow->addWidget(m_tolHi);
    tolRow->addStretch();
    methodForm->addRow(QStringLiteral("公差 (mm)"), tolRow);

    m_devColor3d = new QCheckBox(QStringLiteral("3D 偏差着色（在 3D 视窗同步显示测量区域）"),
                                 methodGroup);
    m_devColor3d->setObjectName(QStringLiteral("measure_dev3d"));
    m_devColor3d->setStyleSheet(QStringLiteral("font-size: %1px;").arg(Theme::FONT_HINT));
    methodForm->addRow(QString(), m_devColor3d);

    auto* btnRow = new QHBoxLayout();
    m_measureBtn = new QPushButton(QStringLiteral("测量"), methodGroup);
    m_measureBtn->setObjectName(QStringLiteral("measure_run"));
    m_measureBtn->setStyleSheet(Theme::primaryButtonStyle());
    btnRow->addWidget(m_measureBtn);
    m_repeatAddBtn = new QPushButton(QStringLiteral("加入重复性"), methodGroup);
    m_repeatAddBtn->setObjectName(QStringLiteral("measure_repeat_add"));
    m_repeatAddBtn->setStyleSheet(Theme::secondaryButtonStyle());
    btnRow->addWidget(m_repeatAddBtn);
    btnRow->addStretch();
    methodForm->addRow(QString(), btnRow);

    m_measureHint = new QLabel(methodGroup);
    m_measureHint->setObjectName(QStringLiteral("measure_hint"));
    m_measureHint->setWordWrap(true);
    m_measureHint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                     .arg(Theme::ERROR).arg(Theme::FONT_HINT));
    methodForm->addRow(QString(), m_measureHint);
    pageLayout->addWidget(methodGroup);

    // ── results ──
    m_measureTable = new QTableWidget(0, 5, page);
    m_measureTable->setObjectName(QStringLiteral("measure_table"));
    m_measureTable->setHorizontalHeaderLabels({ QStringLiteral("方法"), QStringLiteral("数值"),
                                                QStringLiteral("单位"), QStringLiteral("点数"),
                                                QStringLiteral("可信度") });
    m_measureTable->verticalHeader()->setVisible(false);
    m_measureTable->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_measureTable->setSelectionMode(QAbstractItemView::NoSelection);
    m_measureTable->horizontalHeader()->setStretchLastSection(true);
    m_measureTable->setStyleSheet(
        QStringLiteral("QTableWidget { background: %1; border: 1px solid %2;"
                       " border-radius: %3px; font-size: %4px; }"
                       "QHeaderView::section { background: %5; border: none;"
                       " padding: 5px; font-size: %4px; }")
            .arg(Theme::BG_CARD).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS)
            .arg(Theme::FONT_HINT).arg(Theme::BG_MAIN));
    pageLayout->addWidget(m_measureTable, 1);

    // ── repeatability series (session memory only, never written to disk) ──
    auto* seriesGroup = new QGroupBox(QStringLiteral("重复性序列（仅本次运行）"), page);
    auto* seriesForm = new QFormLayout(seriesGroup);
    m_seriesCombo = new ArrowComboBox(seriesGroup);
    m_seriesCombo->setObjectName(QStringLiteral("measure_series_combo"));
    m_seriesCombo->setStyleSheet(Theme::comboBoxStyle());
    seriesForm->addRow(QStringLiteral("序列"), m_seriesCombo);

    m_seriesSummary = new QLabel(QStringLiteral("—"), seriesGroup);
    m_seriesSummary->setObjectName(QStringLiteral("measure_series_summary"));
    m_seriesSummary->setWordWrap(true);
    m_seriesSummary->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                                       .arg(Theme::TEXT_BODY).arg(Theme::FONT_HINT));
    seriesForm->addRow(QStringLiteral("统计"), m_seriesSummary);

    auto* clearSeriesBtn = new QPushButton(QStringLiteral("清空序列"), seriesGroup);
    clearSeriesBtn->setStyleSheet(Theme::secondaryButtonStyle());
    seriesForm->addRow(QString(), clearSeriesBtn);
    pageLayout->addWidget(seriesGroup);

    stack->addWidget(page);

    connect(m_measureBtn, &QPushButton::clicked, this, &ToolsPanel::runMeasurement);
    connect(m_repeatAddBtn, &QPushButton::clicked,
            this, &ToolsPanel::addLastToRepeatSeries);
    connect(m_roiClearBtn, &QPushButton::clicked,
            this, &ToolsPanel::clearMeasurementRois);
    connect(m_seriesCombo, QOverload<int>::of(&QComboBox::currentIndexChanged),
            this, [this](int) { refreshSeriesUi(); });
    connect(clearSeriesBtn, &QPushButton::clicked, this, [this]() {
        m_series.clear();
        refreshSeriesUi();
        emit measurementUpdated(buildSnapshot());
    });
    // The tolerance fields feed the run chart (mean ±3σ plus the tolerance
    // lines), so a change re-publishes the snapshot without re-measuring.
    for (QDoubleSpinBox* spin : { m_tolLo, m_tolHi })
        connect(spin, QOverload<double>::of(&QDoubleSpinBox::valueChanged),
                this, [this](double) { emit measurementUpdated(buildSnapshot()); });
    connect(m_tolEnable, &QCheckBox::toggled, this,
            [this](bool) { emit measurementUpdated(buildSnapshot()); });
    // The 3D-colouring switch has a twin in the 3D view's toolbar; either one
    // drives the same state and the second is kept in step by MainWindow.
    connect(m_devColor3d, &QCheckBox::toggled, this, [this](bool on) {
        emit deviationColoringChanged(on);
        if (m_hasLast)
            runMeasurement();   // re-colour the last result right away
    });
    refreshSeriesUi();
}

void ToolsPanel::setDeviationColoring(bool on)
{
    if (!m_devColor3d || m_devColor3d->isChecked() == on)
        return;
    {
        // Setting the box must not bounce straight back as deviationColoringChanged.
        const QSignalBlocker block(m_devColor3d);
        m_devColor3d->setChecked(on);
    }
    if (m_hasLast)
        runMeasurement();
}

void ToolsPanel::setMeasurementCloud(const FrameBuffer::DoubleBuf& grid, int gridW,
                                     int gridH, int imageW, int imageH)
{
    m_measureGrid = grid;                 // refcount bump, no copy
    m_measureGridW = gridW;
    m_measureGridH = gridH;
    m_imageW = imageW;
    m_imageH = imageH;
    if (m_measureCloudLabel) {
        int valid = 0;
        if (grid && gridW > 0 && gridH > 0) {
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
        m_measureCloudLabel->setText(
            gridW > 0 ? QStringLiteral("%1 × %2 网格，%3 个有效点")
                            .arg(gridW).arg(gridH).arg(valid)
                      : QStringLiteral("尚未采集（先在主窗口点击「拍照」）"));
    }
    // A new capture invalidates the previous ROI selection: the rectangles are
    // in image pixels and the new frame may have a different size.
    if (m_imageW > 0 && m_imageH > 0 && !m_roiRects.isEmpty()) {
        m_roiRects.clear();
        m_roiPoints[0].clear();
        m_roiPoints[1].clear();
        m_roiCells[0].clear();
        m_roiCells[1].clear();
        emit roisChanged({}, {});
    }
    // A measurement describes one frame: the numbers, the deviation map and the
    // 3D overlay all have to go when a new frame arrives.  The repeatability
    // series deliberately survives — accumulating across captures is its point.
    resetMeasurementState();
    updateMeasureHint();
    emit measurementUpdated(buildSnapshot());
}

void ToolsPanel::refreshRoiPoints()
{
    for (int i = 0; i < 2; ++i) {
        m_roiPoints[i].clear();
        m_roiCells[i].clear();
    }
    if (!m_measureGrid || m_measureGridW <= 0 || m_measureGridH <= 0
        || m_imageW <= 0 || m_imageH <= 0) {
        return;
    }
    // The ROI was dragged in image pixels; the point map may live on its own
    // resolution, so the rectangle is scaled into grid cells.
    const double sx = static_cast<double>(m_measureGridW) / m_imageW;
    const double sy = static_cast<double>(m_measureGridH) / m_imageH;
    for (int i = 0; i < m_roiRects.size() && i < 2; ++i) {
        const QRect r = m_roiRects[i];
        const int x0 = static_cast<int>(std::floor(r.left() * sx));
        const int y0 = static_cast<int>(std::floor(r.top() * sy));
        const int x1 = static_cast<int>(std::ceil((r.right() + 1) * sx)) - 1;
        const int y1 = static_cast<int>(std::ceil((r.bottom() + 1) * sy)) - 1;
        m_roiPoints[i] = MeasureTools::pointsInRoiIndexed(
            *m_measureGrid, m_measureGridW, m_measureGridH, x0, y0, x1, y1,
            &m_roiCells[i]);
    }
}

void ToolsPanel::onRoiSelected(const QRect& rect)
{
    if (!m_measureGrid || m_imageW <= 0) {
        m_measureHint->setText(QStringLiteral("尚未采集点云，请先在主窗口拍摄一张。"));
        return;
    }
    if (rect.width() < 4 || rect.height() < 4)
        return;
    // Two ROIs are supported (datum + measured).  A third drag starts over so
    // the selection never gets stuck.
    if (m_roiRects.size() >= 2)
        m_roiRects.clear();
    m_roiRects.push_back(rect);
    refreshRoiPoints();
    emit roisChanged(m_roiRects, roiLabels());
    updateMeasureHint();
}

void ToolsPanel::clearMeasurementRois()
{
    m_roiRects.clear();
    for (int i = 0; i < 2; ++i) {
        m_roiPoints[i].clear();
        m_roiCells[i].clear();
    }
    emit roisChanged({}, {});
    updateMeasureHint();
}

void ToolsPanel::updateMeasureHint()
{
    if (!m_measureRoiLabel)
        return;
    QStringList parts;
    const QStringList labels = roiLabels();
    for (int i = 0; i < m_roiRects.size(); ++i) {
        const QRect r = m_roiRects[i];
        parts << QStringLiteral("%1: (%2,%3)-(%4,%5)，%6 点")
                     .arg(labels[i])
                     .arg(r.left()).arg(r.top()).arg(r.right()).arg(r.bottom())
                     .arg(m_roiPoints[i].size());
    }
    m_measureRoiLabel->setText(parts.isEmpty()
        ? QStringLiteral("未选择 — 在右侧 2D 视图上按住左键拖框（依次为 ROI A、ROI B）")
        : parts.join(QStringLiteral("；")));
}

QStringList ToolsPanel::roiLabels() const
{
    QStringList labels;
    for (int i = 0; i < m_roiRects.size(); ++i)
        labels << QStringLiteral("ROI %1").arg(QChar(QLatin1Char('A').unicode() + i));
    return labels;
}

void ToolsPanel::resetMeasurementState()
{
    // Every run starts from a clean display state: a stale deviation map or
    // annotation from a previous method would be worse than an empty page.
    if (m_measureHint)
        m_measureHint->clear();
    if (m_measureTable)
        m_measureTable->setRowCount(0);
    m_lastRows.clear();
    m_lastKey.clear();
    m_lastPrimary = 0.0;
    m_hasLast = false;
    m_devSamples.clear();
    m_annotations.clear();
    m_section.clear();
    m_sectionStep = 0.0;
    m_cloudColors.reset();
    m_hasPlane = false;
    m_hasBox = false;
    m_pageFooter.clear();
    m_devLo = m_devHi = 0.0;
    m_devRobust = false;
    m_devClipped = 0;
}

void ToolsPanel::runMeasurement()
{
    const int method = m_measureMethod ? m_measureMethod->currentIndex() : 0;

    resetMeasurementState();

    auto addRow = [this](const QString& m, const QString& v, const QString& u,
                         int pts, const QString& conf) {
        m_lastRows.push_back({ m, v, u, pts, conf });
    };
    auto setPrimary = [this](const QString& key, double value) {
        m_lastKey = key;
        m_lastPrimary = value;
        m_hasLast = true;
    };
    // Pushes the accumulated rows into the table and re-publishes the snapshot
    // to the views.  Every exit path of this function goes through here, so the
    // table and the display pages can never disagree about what was measured.
    auto publish = [this]() {
        m_measureTable->setRowCount(static_cast<int>(m_lastRows.size()));
        for (int i = 0; i < m_lastRows.size(); ++i) {
            const Measurement::ResultRow& r = m_lastRows[i];
            const QString cols[5] = { r.method, r.value, r.unit,
                                      QString::number(r.points), r.confidence };
            for (int c = 0; c < 5; ++c) {
                auto* item = new QTableWidgetItem(cols[c]);
                if (c >= 1 && c <= 3)
                    item->setTextAlignment(Qt::AlignRight | Qt::AlignVCenter);
                m_measureTable->setItem(i, c, item);
            }
        }
        m_measureTable->resizeColumnsToContents();
        emit measurementUpdated(buildSnapshot());
    };

    if (!m_measureGrid || m_measureGridW <= 0 || m_measureGridH <= 0) {
        m_measureHint->setText(QStringLiteral("尚未采集点云：请先在主窗口点击「拍照」。"));
        publish();
        return;
    }

    // Fills the deviation page state from a per-point residual vector that is
    // index-aligned with the grid-cell index list.  The colour limits are the
    // MAD-based ±3σ band (Python mviz's `robust_limits`), not percentiles — a
    // single flyer must not squash the whole range.
    auto fillDeviation = [this](const std::vector<double>& dev,
                                const std::vector<std::size_t>& cells,
                                bool coolWarm, const QString& unit) {
        m_devSamples.clear();
        m_devSamples.reserve(static_cast<int>(dev.size()));
        const int gw = m_measureGridW;
        for (std::size_t k = 0; k < dev.size() && k < cells.size(); ++k) {
            Measurement::DevSample s;
            s.value = dev[k];
            s.gx = static_cast<int>(cells[k] % static_cast<std::size_t>(gw));
            s.gy = static_cast<int>(cells[k] / static_cast<std::size_t>(gw));
            m_devSamples.push_back(s);
        }
        const MeasureTools::Limits lim = MeasureTools::robustLimits(dev, 3.0);
        m_devLo = lim.lo;
        m_devHi = lim.hi;
        m_devRobust = lim.robust;
        m_devClipped = static_cast<int>(lim.nClipped);
        m_snapshotCoolWarm = coolWarm;
        m_pageFooter = QStringLiteral("色标 %1 = [%2, %3] %4，裁剪 %5 点")
                           .arg(lim.robust ? QStringLiteral("中位数 ±3σ(MAD)")
                                           : QStringLiteral("1–99% 分位"))
                           .arg(fmt4(lim.lo)).arg(fmt4(lim.hi))
                           .arg(unit).arg(lim.nClipped);
    };

    // Per-point colour for the whole captured cloud, relative to `plane` (P4).
    // The mapping itself is deliberately NOT here: it lives in MeasureTools
    // (pure logic) so its index alignment with PointCloudUtils::filterValidPoints
    // is unit-tested instead of only being claimed.
    auto fillCloudColors = [this](const MeasureTools::Plane& plane, bool coolWarm) {
        m_cloudColors.reset();
        if (!m_devColor3d || !m_devColor3d->isChecked() || !plane.valid
            || !m_measureGrid || m_measureGridW <= 0 || m_measureGridH <= 0)
            return;
        std::vector<std::size_t> highlight = m_roiCells[0];
        highlight.insert(highlight.end(), m_roiCells[1].begin(), m_roiCells[1].end());
        m_cloudColors = std::make_shared<const std::vector<std::array<float, 3>>>(
            MeasureTools::cloudDeviationColors(*m_measureGrid, m_measureGridW,
                                               m_measureGridH, plane, m_devLo, m_devHi,
                                               coolWarm, highlight));
    };

    // Concatenates the two ROIs (datum first) — used by the plane-pair methods.
    auto bothRois = [this](std::vector<MeasureTools::Vec3>& pts,
                           std::vector<std::size_t>& cells) {
        pts = m_roiPoints[0];
        cells = m_roiCells[0];
        pts.insert(pts.end(), m_roiPoints[1].begin(), m_roiPoints[1].end());
        cells.insert(cells.end(), m_roiCells[1].begin(), m_roiCells[1].end());
    };

    auto roiCenter = [this](int roi) {
        std::array<double, 3> c{ 0.0, 0.0, 0.0 };
        const std::vector<MeasureTools::Vec3>& p = m_roiPoints[roi];
        if (p.empty())
            return c;
        for (const MeasureTools::Vec3& v : p)
            for (int k = 0; k < 3; ++k)
                c[k] += v[k];
        for (int k = 0; k < 3; ++k)
            c[k] /= static_cast<double>(p.size());
        return c;
    };

    QString hint;
    switch (method) {
    case 0: {   // 平面度
        const std::vector<MeasureTools::Vec3>& pts = m_roiPoints[0];
        if (pts.size() < 3) {
            hint = QStringLiteral("平面度需要在 ROI A 内至少 3 个点，当前 %1 个。")
                       .arg(pts.size());
            break;
        }
        const MeasureTools::Flatness f = MeasureTools::flatness(pts, 3.0);
        if (!f.valid) {
            hint = QString::fromStdString(f.message);
            break;
        }
        addRow(QStringLiteral("平面度 LSQ PV"), fmt4(f.lsqPv), QStringLiteral("mm"),
               static_cast<int>(f.used), confidenceFor(static_cast<int>(f.used), f.lsqRms));
        addRow(QStringLiteral("平面度 LSQ RMS"), fmt4(f.lsqRms), QStringLiteral("mm"),
               static_cast<int>(f.used), confidenceFor(static_cast<int>(f.used), f.lsqRms));
        addRow(QStringLiteral("平面度 最小区域 PV"), fmt4(f.mzPv), QStringLiteral("mm"),
               static_cast<int>(f.used), confidenceFor(static_cast<int>(f.used), f.lsqRms));
        addRow(QStringLiteral("倾斜角"), fmt4(f.tiltDeg), QStringLiteral("°"),
               static_cast<int>(f.used), confidenceFor(static_cast<int>(f.used), f.lsqRms));
        setPrimary(QStringLiteral("平面度 最小区域 PV"), f.mzPv);

        fillDeviation(f.dev, m_roiCells[0], true, QStringLiteral("mm"));
        fillCloudColors(f.plane, true);
        // Section along the ROI's principal direction, for the 截面轮廓 page.
        const MeasureTools::SectionProfile sec = MeasureTools::sectionProfile(pts, 64);
        if (sec.valid) {
            m_section = sec.points;
            m_sectionStep = sec.stepMm;
        }
        // 3D + 尺寸总图 annotation.
        m_hasPlane = true;
        m_planePoint = roiCenter(0);
        m_planeNormal = f.plane.normal;
        const QRect r = m_roiRects.value(0);
        m_annotations.push_back({ QStringLiteral("平面度 PV %1 mm").arg(fmt4(f.mzPv)),
                                  QPoint(r.center().x(), r.center().y()), false });
        updateMeasureHint();
        publish();
        return;
    }
    case 1: {   // 面到面高度（中位数）
        if (m_roiPoints[0].size() < 3 || m_roiPoints[1].size() < 3) {
            hint = QStringLiteral("需要两个测量区域：在 2D 视图上先后拖出 ROI A（基准）"
                                  "与 ROI B（被测），当前 %1 / %2 点。")
                       .arg(m_roiPoints[0].size()).arg(m_roiPoints[1].size());
            break;
        }
        const MeasureTools::Height h =
            MeasureTools::heightBetween(m_roiPoints[0], m_roiPoints[1], 3.0);
        if (!h.valid) {
            hint = QString::fromStdString(h.message);
            break;
        }
        addRow(QStringLiteral("面到面高度(中位数)"), fmt4(h.value), QStringLiteral("mm"),
               static_cast<int>(h.usedTarget), confidenceFor(static_cast<int>(h.usedTarget), h.rms));
        addRow(QStringLiteral("面到面高度 RMS"), fmt4(h.rms), QStringLiteral("mm"),
               static_cast<int>(h.usedTarget), confidenceFor(static_cast<int>(h.usedTarget), h.rms));
        setPrimary(QStringLiteral("面到面高度(中位数)"), h.value);

        std::vector<MeasureTools::Vec3> pts;
        std::vector<std::size_t> cells;
        bothRois(pts, cells);
        fillDeviation(MeasureTools::deviations(pts, h.ref), cells, true, QStringLiteral("mm"));
        fillCloudColors(h.ref, true);

        const MeasureTools::SectionProfile sec = MeasureTools::sectionProfile(pts, 96);
        if (sec.valid) {
            m_section = sec.points;
            m_sectionStep = sec.stepMm;
        }
        m_hasPlane = true;
        m_planePoint = roiCenter(0);
        m_planeNormal = h.ref.normal;
        const QRect ra = m_roiRects.value(0), rb = m_roiRects.value(1);
        m_annotations.push_back({ QStringLiteral("基准 A"),
                                  QPoint(ra.center().x(), ra.center().y()), false });
        m_annotations.push_back({ QStringLiteral("B 相对 A %1 mm").arg(fmt4(h.value)),
                                  QPoint(rb.center().x(), rb.center().y()), false });
        updateMeasureHint();
        publish();
        return;
    }
    case 2: {   // 面面距离 / 夹角
        if (m_roiPoints[0].size() < 3 || m_roiPoints[1].size() < 3) {
            hint = QStringLiteral("需要两个测量区域（ROI A / ROI B），当前 %1 / %2 点。")
                       .arg(m_roiPoints[0].size()).arg(m_roiPoints[1].size());
            break;
        }
        // 3° is the user-facing parallel threshold (the Python tool ships 5°).
        const MeasureTools::PlanePair pp =
            MeasureTools::planePair(m_roiPoints[0], m_roiPoints[1], 3.0, 3.0);
        if (!pp.valid) {
            hint = QString::fromStdString(pp.message);
            break;
        }
        const int pts = static_cast<int>(pp.usedA + pp.usedB);
        addRow(QStringLiteral("面面夹角"), fmt4(pp.angleDeg), QStringLiteral("°"), pts,
               confidenceFor(pts, -1.0));
        if (pp.parallel) {
            addRow(QStringLiteral("平行面间距"), fmt4(pp.distanceMm), QStringLiteral("mm"), pts,
                   confidenceFor(pts, -1.0));
            setPrimary(QStringLiteral("平行面间距"), pp.distanceMm);
        } else {
            addRow(QStringLiteral("夹角 ≥ 3°：不给出间距"), QStringLiteral("—"),
                   QStringLiteral("mm"), pts, QStringLiteral("—"));
            setPrimary(QStringLiteral("面面夹角"), pp.angleDeg);
        }

        std::vector<MeasureTools::Vec3> p2;
        std::vector<std::size_t> c2;
        bothRois(p2, c2);
        fillDeviation(MeasureTools::deviations(p2, pp.planeA), c2, true, QStringLiteral("mm"));
        fillCloudColors(pp.planeA, true);

        m_hasPlane = true;
        m_planePoint = roiCenter(0);
        m_planeNormal = pp.planeA.normal;
        const QRect ra = m_roiRects.value(0), rb = m_roiRects.value(1);
        m_annotations.push_back({ QStringLiteral("A"), QPoint(ra.center().x(), ra.center().y()),
                                  false });
        m_annotations.push_back({ QStringLiteral("B：夹角 %1°").arg(fmt4(pp.angleDeg)),
                                  QPoint(rb.center().x(), rb.center().y()), false });
        updateMeasureHint();
        publish();
        return;
    }
    case 3: {   // 圆 / 孔径
        const std::vector<MeasureTools::Vec3>& pts = m_roiPoints[0];
        if (pts.size() < 5) {
            hint = QStringLiteral("圆拟合需要在 ROI A 内至少 5 个点，当前 %1 个。")
                       .arg(pts.size());
            break;
        }
        // Two MAD rejection passes, as in the Python tool.
        const MeasureTools::Circle c = MeasureTools::fitCircle(pts, 2, 2.5);
        if (!c.valid) {
            hint = QString::fromStdString(c.message);
            break;
        }
        addRow(QStringLiteral("直径"), fmt4(c.diameter), QStringLiteral("mm"),
               static_cast<int>(c.used), confidenceFor(static_cast<int>(c.used), c.rms));
        addRow(QStringLiteral("半径"), fmt4(c.radius), QStringLiteral("mm"),
               static_cast<int>(c.used), confidenceFor(static_cast<int>(c.used), c.rms));
        addRow(QStringLiteral("圆度(半径极差)"), fmt4(c.roundness), QStringLiteral("mm"),
               static_cast<int>(c.used), confidenceFor(static_cast<int>(c.used), c.rms));
        addRow(QStringLiteral("圆心"), QStringLiteral("(%1, %2, %3)")
                   .arg(fmt4(c.center[0])).arg(fmt4(c.center[1])).arg(fmt4(c.center[2])),
               QStringLiteral("mm"), static_cast<int>(c.used),
               confidenceFor(static_cast<int>(c.used), c.rms));
        setPrimary(QStringLiteral("直径"), c.diameter);

        // The deviation page shows the residual radius for a circle: same
        // signed-distance idea, measured from the fitted circle instead.
        std::vector<double> radial(pts.size());
        for (std::size_t k = 0; k < pts.size(); ++k) {
            const double dx = pts[k][0] - c.center[0];
            const double dy = pts[k][1] - c.center[1];
            const double dz = pts[k][2] - c.center[2];
            radial[k] = std::sqrt(dx * dx + dy * dy + dz * dz) - c.radius;
        }
        fillDeviation(radial, m_roiCells[0], false, QStringLiteral("mm"));

        const QRect r = m_roiRects.value(0);
        m_annotations.push_back({ QStringLiteral("⌀%1 mm").arg(fmt4(c.diameter)),
                                  QPoint(r.center().x(), r.center().y()), false });
        m_hasPlane = true;
        m_planePoint = c.center;
        m_planeNormal = c.normal;
        updateMeasureHint();
        publish();
        return;
    }
    case 4: {   // 包围盒
        const std::vector<MeasureTools::Vec3>& pts = m_roiPoints[0];
        if (pts.size() < 4) {
            hint = QStringLiteral("包围盒需要在 ROI A 内至少 4 个点，当前 %1 个。")
                       .arg(pts.size());
            break;
        }
        const MeasureTools::BoundingBox b = MeasureTools::pcaBoundingBox(pts);
        if (!b.valid) {
            hint = QString::fromStdString(b.message);
            break;
        }
        const int used = static_cast<int>(b.used);
        addRow(QStringLiteral("长"), fmt4(b.length), QStringLiteral("mm"), used,
               confidenceFor(used, -1.0));
        addRow(QStringLiteral("宽"), fmt4(b.width), QStringLiteral("mm"), used,
               confidenceFor(used, -1.0));
        addRow(QStringLiteral("高"), fmt4(b.height), QStringLiteral("mm"), used,
               confidenceFor(used, -1.0));
        addRow(QStringLiteral("中心"), QStringLiteral("(%1, %2, %3)")
                   .arg(fmt4(b.center[0])).arg(fmt4(b.center[1])).arg(fmt4(b.center[2])),
               QStringLiteral("mm"), used, confidenceFor(used, -1.0));
        setPrimary(QStringLiteral("长"), b.length);

        // Axis-aligned extent of the ROI, used to place the 3D marker.
        m_hasBox = true;
        for (int k = 0; k < 3; ++k) {
            m_boxMin[k] = std::numeric_limits<double>::max();
            m_boxMax[k] = std::numeric_limits<double>::lowest();
        }
        for (const MeasureTools::Vec3& v : pts) {
            for (int k = 0; k < 3; ++k) {
                m_boxMin[k] = std::min(m_boxMin[k], v[k]);
                m_boxMax[k] = std::max(m_boxMax[k], v[k]);
            }
        }
        const QRect r = m_roiRects.value(0);
        m_annotations.push_back(
            { QStringLiteral("%1 × %2 × %3 mm").arg(fmt4(b.length), fmt4(b.width),
                                                     fmt4(b.height)),
              QPoint(r.center().x(), r.center().y()), false });
        updateMeasureHint();
        publish();
        return;
    }
    default:    // 重复性统计
        break;
    }

    if (!hint.isEmpty()) {
        m_measureHint->setText(hint);
        updateMeasureHint();
        publish();
        return;
    }

    // ── 重复性统计: statistics of the series selected in the combo box ──
    const QString name = m_seriesCombo ? m_seriesCombo->currentText() : QString();
    if (name.isEmpty() || !m_series.contains(name) || m_series.value(name).isEmpty()) {
        m_measureHint->setText(QStringLiteral(
            "当前没有重复性数据：先测一个尺寸，再点「加入重复性」（可反复采样）。"));
        updateMeasureHint();
        publish();
        return;
    }
    const QVector<double>& vals = m_series.value(name);
    const MeasureTools::Repeatability rep =
        MeasureTools::repeatability(std::vector<double>(vals.begin(), vals.end()));
    if (rep.valid) {
        const int n = static_cast<int>(rep.n);
        addRow(QStringLiteral("采样数 n"), QString::number(n), QString(), n,
               confidenceFor(n, -1.0));
        addRow(QStringLiteral("均值"), fmt4(rep.mean), QStringLiteral("mm"), n,
               confidenceFor(n, -1.0));
        addRow(QStringLiteral("标准差 σ"), fmt4(rep.stdDev), QStringLiteral("mm"), n,
               confidenceFor(n, -1.0));
        addRow(QStringLiteral("极差"), fmt4(rep.range), QStringLiteral("mm"), n,
               confidenceFor(n, -1.0));
        addRow(QStringLiteral("±3σ"), QStringLiteral("±%1").arg(fmt4(rep.sixSigma / 2.0)),
               QStringLiteral("mm"), n, confidenceFor(n, -1.0));
        addRow(QStringLiteral("最小 / 最大"),
               QStringLiteral("%1 / %2").arg(fmt4(rep.min), fmt4(rep.max)),
               QStringLiteral("mm"), n, confidenceFor(n, -1.0));
        addRow(QStringLiteral("最大偏差"), fmt4(rep.maxDev), QStringLiteral("mm"), n,
               confidenceFor(n, -1.0));
    } else {
        hint = QStringLiteral("序列「%1」的有效样本不足。").arg(name);
    }
    m_pageFooter = hint.isEmpty()
        ? QStringLiteral("序列「%1」：n=%2，均值 %3，σ %4（仅本次运行，未写入磁盘）")
              .arg(name).arg(rep.n).arg(fmt4(rep.mean)).arg(fmt4(rep.stdDev))
        : QString();
    updateMeasureHint();
    publish();
}

void ToolsPanel::addLastToRepeatSeries()
{
    if (!m_hasLast || m_lastKey.isEmpty()) {
        m_measureHint->setText(QStringLiteral(
            "先执行一次测量（平面度 / 高度 / 间距 / 直径 / 长），再把结果加入序列。"));
        return;
    }
    // Session-only series: the accumulator lives in this panel's memory and is
    // deliberately never written to disk.
    m_series[m_lastKey].append(m_lastPrimary);
    m_measureHint->clear();
    refreshSeriesUi();
    if (m_seriesCombo) {
        const int idx = m_seriesCombo->findText(m_lastKey);
        if (idx >= 0 && m_seriesCombo->currentIndex() != idx) {
            QSignalBlocker block(m_seriesCombo);   // avoid a re-entrant refresh
            m_seriesCombo->setCurrentIndex(idx);
        }
    }
    emit measurementUpdated(buildSnapshot());
}

void ToolsPanel::refreshSeriesUi()
{
    if (!m_seriesCombo)
        return;
    const QString keep = m_seriesCombo->currentText();
    {
        QSignalBlocker block(m_seriesCombo);
        m_seriesCombo->clear();
        for (auto it = m_series.constBegin(); it != m_series.constEnd(); ++it) {
            if (!it.value().isEmpty())
                m_seriesCombo->addItem(it.key());
        }
        const int idx = m_seriesCombo->findText(keep);
        if (idx >= 0)
            m_seriesCombo->setCurrentIndex(idx);
    }
    if (!m_seriesSummary)
        return;
    const QString name = m_seriesCombo->currentText();
    if (name.isEmpty() || !m_series.contains(name)) {
        m_seriesSummary->setText(QStringLiteral("—"));
        return;
    }
    const QVector<double>& vals = m_series.value(name);
    const MeasureTools::Repeatability rep =
        MeasureTools::repeatability(std::vector<double>(vals.begin(), vals.end()));
    m_seriesSummary->setText(
        rep.valid ? QStringLiteral("n=%1  均值 %2 mm  σ %3 mm  极差 %4 mm  ±3σ %5 mm")
                        .arg(rep.n).arg(fmt4(rep.mean)).arg(fmt4(rep.stdDev))
                        .arg(fmt4(rep.range)).arg(fmt4(3.0 * rep.stdDev))
                  : QStringLiteral("样本不足（n=%1）").arg(rep.n));
}

Measurement::Snapshot ToolsPanel::buildSnapshot() const
{
    Measurement::Snapshot s;
    s.valid = !m_lastRows.isEmpty();
    s.title = m_measureMethod ? m_measureMethod->currentText() : QString();
    s.footer = m_pageFooter;

    s.devSamples = m_devSamples;
    s.gridW = m_measureGridW;
    s.gridH = m_measureGridH;
    s.limitLo = m_devLo;
    s.limitHi = m_devHi;
    s.robustLimits = m_devRobust;
    s.clipped = m_devClipped;
    s.unit = QStringLiteral("mm");
    s.coolWarm = m_snapshotCoolWarm;

    s.annotations = m_annotations;

    s.section = m_section;
    s.sectionStep = m_sectionStep;
    s.sectionPoints = static_cast<int>(m_section.size());

    // The run chart always shows the series picked in the combo box, which is
    // the one the user is accumulating into.
    if (m_seriesCombo) {
        const QString name = m_seriesCombo->currentText();
        if (!name.isEmpty() && m_series.contains(name)) {
            s.seriesName = name;
            s.series = m_series.value(name);
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

    // ── 3D payload ──
    s.cloudColors = m_cloudColors;   // refcount bump, never an element copy
    s.hasCloudColors = m_cloudColors && !m_cloudColors->empty();
    s.hasPlane = m_hasPlane;
    s.planePoint = m_planePoint;
    s.planeNormal = m_planeNormal;
    s.hasRoiBox = m_hasBox;
    s.boxMin = m_boxMin;
    s.boxMax = m_boxMax;
    s.label = s.title;
    return s;
}
