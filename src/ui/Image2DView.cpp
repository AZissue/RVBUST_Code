#include "ui/Image2DView.h"
#include "logic/RuntimeLog.h"
#include "ui/Theme.h"
#include "ui/ViewOverlay.h"   // 与 3D 视窗共用的浮层（玻璃）按钮/标签组件（T-003）
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QWheelEvent>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPen>
#include <QFont>
#include <QApplication>
#include <QPushButton>
#include <QSignalBlocker>
#include <QTimer>
#include <algorithm>
#include <cmath>
#include <functional>
#include <utility>

namespace {

// A left-drag shorter than this is still a click (pixel picking must keep
// working); the Python tool uses the same 4 px gate for ROI drags.
constexpr int kRoiMinDrag = 4;

// ── 浮层的「毛玻璃」底（T-001 判据 3）──────────────────────────────────
// 浮层控件本身（圆角、模糊铺设）已抽到共用的 ui/ViewOverlay.h（T-003），
// 圆角常量只有那边一处定义（ViewOverlay::kGlassRadius，与 QSS 的 8px 同值）。
// 廉价的高斯近似：先把要铺的那一小块缩到 1/8（FastTransformation，取平均），
// 再平滑放大回原尺寸。浮层控件只有几十像素高，这一对缩放在微秒级——比一次
// 真正的高斯卷积便宜两个数量级，也不会把 30fps 的实时预览拖住。
constexpr int kGlassBlurFactor = 8;

// Qt 5.14 的 QWidget::mapTo() / mapFrom() 有个会崩的前提（源码见
// qtbase/src/widgets/kernel/qwidget.cpp）：
//
//     const QWidget *w = this;
//     while (w != parent) {                       // 条件里没有 w！
//         Q_ASSERT_X(w, "QWidget::mapTo(...)", "parent must be in parent hierarchy");
//         p = w->mapToParent(p);
//         w = w->parentWidget();
//     }
//
// parent 不在祖先链上时，循环会一直走到顶层控件之外的 nullptr，而那句断言在
// Release（NDEBUG）里被编掉，于是对空指针调用 mapToParent()，解引用
// data->crect —— 0xC0000005（故障指令落在 Qt5Widgets.dll，A 的日志里就是这个码、
// 这个模块）。所以这里自己先把祖先关系确认掉，再调 Qt 的映射函数。
bool isAncestor(const QWidget* ancestor, const QWidget* w)
{
    for (const QWidget* p = w ? w->parentWidget() : nullptr; p; p = p->parentWidget()) {
        if (p == ancestor)
            return true;
    }
    return false;
}

} // namespace

Image2DView::Image2DView(QWidget* parent)
    : QWidget(parent)
{
    setMinimumSize(400, 300);
    // T-002 判据 6：2D 视窗四周原来那圈 2px 描边（工具栏就贴在内底边）去掉。
    // 工具栏容器 #view2d_page_bar 保持无描边。

    auto* mainLayout = new QVBoxLayout(this);
    mainLayout->setContentsMargins(0, 0, 0, 0);
    mainLayout->setSpacing(0);

    // Image display area — fills the whole view (no title bar), so the image
    // gets as much space as possible.
    m_imageLabel = new QLabel(this);
    m_imageLabel->setAlignment(Qt::AlignCenter);
    m_imageLabel->setStyleSheet(QStringLiteral("background-color: %1; border: none;").arg(Theme::BG_DARK_2D));
    m_imageLabel->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    mainLayout->addWidget(m_imageLabel, 1);

    // Overlay labels (title top-left, zoom top-right) float over the image and
    // are transparent to mouse events so pixel picking still works through them.
    // T-001 判据 3：无边框、无实心底色，底是背后画面的模糊副本（标题保留加粗）。
    const auto glassSource = [this](const QWidget* w) { return overlayBlurUnder(w); };

    auto* titleLabel = new GlassLabel(this);
    titleLabel->setText(QStringLiteral("2D 实时图像"));
    titleLabel->setGlassSource(glassSource);
    titleLabel->setStyleSheet(Theme::viewOverlayLabelStyle()
                              + QStringLiteral("QLabel { font-weight: 600; }"));
    titleLabel->setAttribute(Qt::WA_TransparentForMouseEvents);
    m_titleLabel = titleLabel;
    m_glassWidgets.push_back(titleLabel);

    auto* zoomLabel = new GlassLabel(this);
    zoomLabel->setText(QStringLiteral("适应"));
    zoomLabel->setGlassSource(glassSource);
    zoomLabel->setStyleSheet(Theme::viewOverlayLabelStyle());
    zoomLabel->setAttribute(Qt::WA_TransparentForMouseEvents);
    m_zoomLabel = zoomLabel;
    m_glassWidgets.push_back(zoomLabel);

    // 「预览已暂停」提示（第 13 回合）。无操作暂停是刻意设计（把相机让给别的
    // 工具），但在此之前它与"程序卡死"在画面上长得一模一样：现场报的"预览停在
    // 某一帧一会又好了"就是它。所以暂停必须自己说出来，而不是让人猜。
    // 用同一套浮层组件（模糊底 + 白字），保持两个视窗的观感一致。
    auto* pausedHint = new GlassLabel(this);
    pausedHint->setText(QStringLiteral("预览已暂停"));
    pausedHint->setGlassSource(glassSource);
    pausedHint->setStyleSheet(Theme::viewOverlayLabelStyle()
                              + QStringLiteral("QLabel { font-weight: 600; "
                                               "padding: 8px 16px; }"));
    pausedHint->setAlignment(Qt::AlignCenter);
    pausedHint->setAttribute(Qt::WA_TransparentForMouseEvents);
    pausedHint->hide();
    m_pausedHint = pausedHint;
    m_glassWidgets.push_back(pausedHint);

    // Zoom-drag uses a fast (nearest-neighbor) scale; a short debounce timer
    // then re-renders the final frame with smooth scaling.
    m_smoothTimer = new QTimer(this);
    m_smoothTimer->setSingleShot(true);
    m_smoothTimer->setInterval(200);
    connect(m_smoothTimer, &QTimer::timeout, this, [this]() {
        m_smoothRender = true;
        render();
    });

    buildToolbar();
}

void Image2DView::setDisplayImage(const QImage& image)
{
    if (image.isNull())
        return;
    // convertFromImage reuses the existing pixmap's storage when the size and
    // format still match, so a streaming preview does not reallocate a 1.5 MP
    // pixmap 20 times a second.
    if (m_originalPixmap.isNull() || m_originalPixmap.size() != image.size())
        m_originalPixmap = QPixmap::fromImage(image);
    else
        m_originalPixmap.convertFromImage(image);
    m_canvasDirty = true;
}

void Image2DView::updateFrame(const QImage& image, bool preserveView, bool livePreview)
{
    if (image.isNull()) return;

    m_cameraImage = image;

    // Frozen for an offline tool: the real frame is kept (so unfreezing brings
    // it straight back) but nothing on screen changes.
    if (m_frozen)
        return;

    setDisplayImage(image);

    if (!preserveView) {
        m_autoFit = true;
        m_zoomLevel = 0.0;
        fitZoom();
    }

    if (livePreview) {
        // Streaming: render this frame with the cheap path and let the existing
        // 200 ms settle timer come back with one smooth, full-quality frame.
        m_livePreview = true;
        m_smoothRender = false;
        m_smoothTimer->start();
    } else {
        // A captured still is not re-rendered a moment later, so it is worth
        // the full-quality scale right away.
        m_livePreview = false;
        m_smoothTimer->stop();
        m_smoothRender = true;
    }
    render();
}


void Image2DView::drawMarkers(const std::vector<std::tuple<float, float, std::string>>& markers)
{
    m_markers = markers;
    m_canvasDirty = true;
    render();
}

void Image2DView::clearMarkers()
{
    m_markers.clear();
    m_canvasDirty = true;
    render();
}

void Image2DView::clear()
{
    m_originalPixmap = QPixmap();
    m_cachedCanvas = QPixmap();
    m_cachedVisible = QPixmap();
    m_markers.clear();
    m_cameraImage = QImage();
    m_canvasDirty = true;
    m_imageLabel->clear();
    setPreviewPausedHint(false, 0);
}

// ── Offline freeze ─────────────────────────────────────────────────────

void Image2DView::setFrozenImage(const QImage& image)
{
    if (image.isNull())
        return;
    m_frozenImage = image;
    m_frozen = true;
    setDisplayImage(image);     // paints the still instead of the live frame
    m_autoFit = true;
    m_zoomLevel = 0.0;
    fitZoom();
    m_canvasDirty = true;
    m_livePreview = false;
    m_smoothRender = true;
    render();
}

void Image2DView::clearFrozenImage()
{
    if (!m_frozen)
        return;
    m_frozen = false;
    m_frozenImage = QImage();

    if (!m_cameraImage.isNull()) {
        // Come back to the last real frame that arrived while frozen.
        setDisplayImage(m_cameraImage);
        m_autoFit = true;
        m_zoomLevel = 0.0;
        fitZoom();
        m_canvasDirty = true;
        m_livePreview = false;
        m_smoothRender = true;
        render();
        return;
    }

    // No real frame to come back to: leave the canvas empty.
    m_originalPixmap = QPixmap();
    m_cachedCanvas = QPixmap();
    m_cachedVisible = QPixmap();
    m_canvasDirty = true;
    m_imageLabel->clear();
    render();
}

// ── 「预览已暂停」提示（第 13 回合）─────────────────────────────────────
//
// 只在"无操作暂停预览"生效期间显示：画面停住是因为我们按设计停掉了取流，不是
// 相机断了、也不是界面卡死。恢复（任何输入）时立刻撤掉。
void Image2DView::setPreviewPausedHint(bool paused, int idleSec)
{
    if (!m_pausedHint)
        return;
    if (!paused) {
        if (m_pausedHint->isVisible())
            m_pausedHint->hide();
        return;
    }
    m_pausedHint->setText(idleSec > 0
        ? QStringLiteral("预览已暂停（无操作 %1 秒）\n移动鼠标或按任意键继续")
              .arg(idleSec)
        : QStringLiteral("预览已暂停\n移动鼠标或按任意键继续"));
    updatePausedHintGeometry();
    m_pausedHint->show();
    m_pausedHint->raise();
    // 暂停期间没有新帧，没有任何别的东西会重画它 —— 第一次上屏要自己触发。
    m_pausedHint->update();
}

void Image2DView::updatePausedHintGeometry()
{
    if (!m_pausedHint)
        return;
    m_pausedHint->adjustSize();
    const int x = std::max(0, (width() - m_pausedHint->width()) / 2);
    const int y = std::max(0, (height() - m_pausedHint->height()) / 2);
    m_pausedHint->move(x, y);
}

// ── Bottom toolbar (相机选择 + 清除 ROI) ──────────────────────────────

void Image2DView::buildToolbar()
{
    auto* bar = new QWidget(this);
    bar->setObjectName(QStringLiteral("view2d_toolbar"));
    auto* row = new QHBoxLayout(bar);
    row->setContentsMargins(0, 0, 0, 0);
    row->setSpacing(4);

    // T-001 判据 3：工具栏按钮同样去掉边框与实心底色，底换成背后画面的模糊副本
    // （和视窗里两个标签用同一个模糊源）。
    const QString style = Theme::viewOverlayButtonStyle();
    const auto glassSource = [this](const QWidget* w) { return overlayBlurUnder(w); };

    // 「相机选择」：左 / 右 / 彩色三台相机各一个互斥小按钮。文字用「相机选择」
    // 打头，让功能名和按钮风格都和现有工具栏一致；未连接或该机型没有这台相机时
    // 按钮禁用（保持可见，比藏起来更好找）。
    auto* caption = new GlassLabel(bar);
    caption->setText(QStringLiteral("相机选择"));
    caption->setGlassSource(glassSource);
    caption->setStyleSheet(Theme::viewOverlayLabelStyle());
    caption->setAttribute(Qt::WA_TransparentForMouseEvents);
    row->addWidget(caption);
    m_glassWidgets.push_back(caption);

    const QStringList names = { QStringLiteral("左相机"), QStringLiteral("右相机"),
                                QStringLiteral("彩色相机") };
    for (int i = 0; i < names.size(); ++i) {
        auto* btn = new GlassButton(bar);
        btn->setText(names[i]);
        btn->setObjectName(QStringLiteral("view2d_camera_%1").arg(i));
        btn->setGlassSource(glassSource);
        btn->setCheckable(true);
        btn->setAutoExclusive(true);
        btn->setChecked(i == static_cast<int>(m_previewCamera));
        btn->setEnabled(false);   // 连接成功后由主窗口按机型放开
        btn->setStyleSheet(style);
        btn->setCursor(Qt::PointingHandCursor);
        btn->setFocusPolicy(Qt::NoFocus);
        connect(btn, &QPushButton::clicked, this, [this, i]() {
            setPreviewCamera(static_cast<PreviewCamera>(i));
            emit previewCameraSelected(i);
        });
        row->addWidget(btn);
        m_cameraButtons.push_back(btn);
        m_glassWidgets.push_back(btn);
    }

    // 清除 ROI（第 7 回合 P3.3）：面板里的「清除区域」保留，视窗工具栏也放一个。
    // 它只发信号——真正的状态在工具面板里，清完由 roisChanged 回到这里擦掉叠加。
    auto* clearBtn = new GlassButton(bar);
    clearBtn->setText(QStringLiteral("清除 ROI"));
    clearBtn->setGlassSource(glassSource);
    clearBtn->setObjectName(QStringLiteral("view2d_clear_roi"));
    clearBtn->setStyleSheet(style);
    clearBtn->setCursor(Qt::PointingHandCursor);
    clearBtn->setFocusPolicy(Qt::NoFocus);
    clearBtn->setEnabled(false);   // 没有 ROI 可清时禁用（比藏起来更好找）
    connect(clearBtn, &QPushButton::clicked, this, &Image2DView::roiClearRequested);
    row->addWidget(clearBtn);
    m_clearRoiBtn = clearBtn;
    m_glassWidgets.push_back(clearBtn);

    bar->adjustSize();
    bar->raise();
    m_toolBar = bar;
    updateToolbarGeometry();
}

void Image2DView::updateToolbarGeometry()
{
    if (!m_toolBar)
        return;
    m_toolBar->adjustSize();
    m_toolBar->move(8, std::max(8, height() - m_toolBar->height() - 8));
    m_toolBar->raise();
}

void Image2DView::setCameraChoices(bool leftAvailable, bool rightAvailable,
                                   bool colorAvailable)
{
    const bool avail[3] = { leftAvailable, rightAvailable, colorAvailable };
    for (int i = 0; i < m_cameraButtons.size() && i < 3; ++i) {
        auto* btn = m_cameraButtons[i];
        if (!btn)
            continue;
        btn->setEnabled(avail[i]);
        // 不可用的相机不能停留在选中态：回退到第一款可用的（左相机总是可用）。
        if (!avail[i] && i == static_cast<int>(m_previewCamera) && leftAvailable) {
            m_previewCamera = PreviewCamera::Left;
            const QSignalBlocker block(btn);
            if (m_cameraButtons[0])
                m_cameraButtons[0]->setChecked(true);
        }
    }
}

void Image2DView::setPreviewCamera(PreviewCamera camera)
{
    m_previewCamera = camera;
    const int idx = static_cast<int>(camera);
    if (idx >= 0 && idx < m_cameraButtons.size() && m_cameraButtons[idx]) {
        const QSignalBlocker block(m_cameraButtons[idx]);
        m_cameraButtons[idx]->setChecked(true);
    }
    if (m_titleLabel) {
        const QString name = camera == PreviewCamera::Right
                                 ? QStringLiteral("右相机")
                                 : (camera == PreviewCamera::Color
                                        ? QStringLiteral("彩色相机")
                                        : QStringLiteral("左相机"));
        m_titleLabel->setText(QStringLiteral("2D 实时图像（%1）").arg(name));
        m_titleLabel->adjustSize();
    }
}

// ── 浮层的模糊底（T-001 判据 3）────────────────────────────────────────
// m_cachedVisible 就是 m_imageLabel 上此刻那张画面，所以控件在画面里的矩形
// 可以直接映射过去；这里只对控件那几十像素做一次降采样+平滑放大，成本与
// 控件面积成正比，和画面大小无关——30fps 的实时预览也扛得住。
//
// 坐标映射（T-001 回归的根因，别再改回去）：**不能**写
//     w->mapTo(m_imageLabel, QPoint(0, 0))
// ——那几个浮层控件（标题/缩放标签是 this 的子控件，工具条按钮在 bar 里面）都
// 不是 m_imageLabel 的后代，m_imageLabel 只是它们的**兄弟**，不在祖先链上。
// Qt 5.14 的 mapTo() 在这种情况下会一路走过顶层控件、在 nullptr 上继续
// mapToParent()（Release 下断言被编掉）→ 0xC0000005（见文件上方 isAncestor 的说明）。
// 正确做法：先映射到**合法祖先** this（button→bar→this / label→this 都在链上），
// 再用 m_imageLabel 在 this 里的位置（m_imageLabel 是 this 的直接子控件，
// pos() 就是它的左上角）换算到画面坐标。
QImage Image2DView::overlayBlurUnder(const QWidget* w) const
{
    // T-010 仪表：本次调用无论走哪条 return，都要把耗时计进去（RAII 守卫）。
    // mutable 成员让 const 方法也能累计；nsecsElapsed() 本身的开销在几十 ns，
    // 相对这里要量的 copy+两次 scaled 可以忽略。
    ++m_overlayCalls;
    m_overlayBlurTimer.start();
    struct BlurMeter {
        const Image2DView* self;
        ~BlurMeter() { self->m_overlayBlurUs += self->m_overlayBlurTimer.nsecsElapsed() / 1000; }
    } blurMeter{this};

    if (!w || !m_imageLabel || m_cachedVisible.isNull())
        return {};
    // 祖先链对不上就别调 Qt 的映射函数：宁可不铺底，也不能让进程崩。
    if (!isAncestor(this, w) || m_imageLabel->parentWidget() != this)
        return {};

    const QPoint originInView = w->mapTo(this, QPoint(0, 0));
    const QRect want(originInView - m_imageLabel->pos(), w->size());
    const QRect have = want.intersected(QRect(QPoint(0, 0), m_cachedVisible.size()));
    if (have.isEmpty())
        return {};

    const QSize small(std::max(1, have.width() / kGlassBlurFactor),
                      std::max(1, have.height() / kGlassBlurFactor));
    const QImage blurred =
        m_cachedVisible.copy(have).toImage()
            .scaled(small, Qt::IgnoreAspectRatio, Qt::FastTransformation)
            .scaled(have.size(), Qt::IgnoreAspectRatio, Qt::SmoothTransformation);

    // 控件有一部分落在画面外时只铺画面内的那块，其余留透明（露出父窗口的像素）。
    QImage out(want.size(), QImage::Format_ARGB32_Premultiplied);
    out.fill(Qt::transparent);
    QPainter p(&out);
    p.drawImage(have.topLeft() - want.topLeft(), blurred);
    ++m_overlayPaints;   // T-010 仪表：返回非空图 = 这次真铺了一层模糊底
    return out;
}

// T-010 仪表：每满 1 s 输出一行，并清零重开窗口。仪表留在代码里（契约冻结）。
void Image2DView::tickOverlayMeter()
{
    if (!m_overlayWindowStarted) {
        m_overlayWindow.restart();
        m_overlayWindowStarted = true;
        return;
    }
    const qint64 windowMs = m_overlayWindow.elapsed();
    if (windowMs < 1000)
        return;

    const quint64 frames = m_overlayFrames > 0 ? m_overlayFrames : 1;
    const double perFrameUs = static_cast<double>(m_overlayBlurUs) / static_cast<double>(frames);
    RuntimeLog::log("[OVERLAY] per_frame_us=%.1f paints=%llu calls=%llu frames=%llu window=%lldms",
                    perFrameUs,
                    static_cast<unsigned long long>(m_overlayPaints),
                    static_cast<unsigned long long>(m_overlayCalls),
                    static_cast<unsigned long long>(m_overlayFrames),
                    static_cast<long long>(windowMs));

    m_overlayBlurUs = 0;
    m_overlayCalls = 0;
    m_overlayPaints = 0;
    m_overlayFrames = 0;
    m_overlayWindow.restart();
}

void Image2DView::updateOverlayBackdrops()
{
    for (QWidget* w : m_glassWidgets) {
        if (w && w->isVisible())
            w->update();
    }
}

void Image2DView::setRois(const QVector<QRect>& rois, const QStringList& labels)
{
    m_rois = rois;
    m_roiLabels = labels;
    if (m_clearRoiBtn)
        m_clearRoiBtn->setEnabled(!rois.isEmpty());
    m_canvasDirty = true;
    render();
}

void Image2DView::clearRois()
{
    m_rois.clear();
    m_roiLabels.clear();
    if (m_clearRoiBtn)
        m_clearRoiBtn->setEnabled(false);
    m_canvasDirty = true;
    render();
}

// ── Rendering (double-buffered Canvas + Visible) ──

void Image2DView::render()
{
    if (m_originalPixmap.isNull()) {
        // 画面没了（clear / 还没收到帧）：浮层也要把上一次的模糊底擦掉。
        updateOverlayBackdrops();
        ++m_overlayFrames;
        tickOverlayMeter();
        return;
    }

    int vw = m_imageLabel->width();
    int vh = m_imageLabel->height();
    if (vw <= 0 || vh <= 0) return;

    m_renderTimer.start();

    double zoom = m_zoomLevel;
    if (zoom <= 0) {
        double zw = static_cast<double>(vw) / m_originalPixmap.width();
        double zh = static_cast<double>(vh) / m_originalPixmap.height();
        zoom = std::min(zw, zh);
    }

    int cw = static_cast<int>(m_originalPixmap.width() * zoom);
    int ch = static_cast<int>(m_originalPixmap.height() * zoom);
    cw = std::max(cw, 1);
    ch = std::max(ch, 1);

    // Layer 1: Canvas (scaled image + markers).  Rebuild only when the image,
    // zoom or markers changed; panning reuses the cached canvas so dragging
    // stays smooth even at high zoom.
    if (m_cachedCanvas.size() != QSize(cw, ch) || m_canvasDirty) {
        if (m_cachedCanvas.size() != QSize(cw, ch))
            m_cachedCanvas = QPixmap(cw, ch);
        m_cachedCanvas.fill(Qt::black);

        QPainter cp(&m_cachedCanvas);
        // Streaming preview: nearest-neighbour scale only.  The 200 ms settle
        // timer comes back with SmoothPixmapTransform once the stream pauses,
        // so the expensive scale runs once per pause instead of 20 times a
        // second.
        cp.setRenderHint(QPainter::SmoothPixmapTransform, m_smoothRender);
        cp.drawPixmap(0, 0, cw, ch, m_originalPixmap);

        for (const auto& [mx, my, label] : m_markers) {
            const int px = static_cast<int>(mx * zoom);
            const int py = static_cast<int>(my * zoom);

            // Compact continuous crosshair (no center gap)
            const int arm = 6;
            QPen pen(QColor(Theme::PRIMARY), 1.5);
            cp.setPen(pen);
            cp.drawLine(px - arm, py, px + arm, py);
            cp.drawLine(px, py - arm, px, py + arm);

            // Label: no background box, just text with a subtle shadow so it
            // stays readable over bright pixels.
            QFont font(QStringLiteral("Microsoft YaHei"), 9);
            font.setBold(true);
            cp.setFont(font);
            const QPoint textPos(px + 8, py + 10);
            cp.setPen(QColor(0, 0, 0, 200));
            cp.drawText(textPos + QPoint(1, 1), QString::fromStdString(label));
            cp.setPen(Qt::white);
            cp.drawText(textPos, QString::fromStdString(label));
        }
        cp.end();
        m_canvasDirty = false;
    }

    // Layer 2: Visible — crop/center Canvas into viewport
    if (m_cachedVisible.size() != QSize(vw, vh)) {
        m_cachedVisible = QPixmap(vw, vh);
    }
    m_cachedVisible.fill(Qt::black);

    // Calculate offset to keep Canvas centered
    int renderOx = m_offsetX;
    int renderOy = m_offsetY;
    // Clamp so at least part of the image shows
    renderOx = std::clamp(renderOx, -cw + 50, vw - 50);
    renderOy = std::clamp(renderOy, -ch + 50, vh - 50);
    m_lastRenderOx = renderOx;
    m_lastRenderOy = renderOy;
    m_lastZoom = zoom;

    QPainter vp(&m_cachedVisible);
    vp.drawPixmap(renderOx, renderOy, m_cachedCanvas);

    // ROI rectangles (A/B) and the in-progress rubber band are painted in the
    // visible layer: they change without invalidating the scaled canvas.
    if (!m_rois.isEmpty() || m_roiPending) {
        vp.setRenderHint(QPainter::Antialiasing, true);
        auto toView = [&](const QRect& r) {
            return QRect(QPoint(renderOx + static_cast<int>(r.left() * zoom),
                                renderOy + static_cast<int>(r.top() * zoom)),
                         QSize(std::max(1, static_cast<int>(r.width() * zoom)),
                               std::max(1, static_cast<int>(r.height() * zoom))));
        };
        for (int i = 0; i < m_rois.size(); ++i) {
            const QRect box = toView(m_rois[i]);
            const QColor col = (i == 0) ? QColor(Theme::PRIMARY) : QColor(Theme::WARNING);
            vp.setPen(QPen(col, 2));
            vp.setBrush(QColor(col.red(), col.green(), col.blue(), 30));
            vp.drawRect(box);
            const QString label = i < m_roiLabels.size()
                ? m_roiLabels[i]
                : QStringLiteral("ROI %1").arg(QChar(QLatin1Char('A').unicode() + i));
            QFont f(QStringLiteral("Microsoft YaHei"), 10);
            f.setBold(true);
            vp.setFont(f);
            const QRect textBox(box.left(), std::max(0, box.top() - 20), 90, 18);
            vp.setPen(Qt::NoPen);
            vp.setBrush(col);
            vp.drawRect(textBox);
            vp.setPen(Qt::white);
            vp.drawText(textBox.adjusted(4, 0, 0, 0), Qt::AlignVCenter | Qt::AlignLeft, label);
        }
        if (m_roiPending && m_roiCurrent.isValid()) {
            const QRect box = toView(m_roiCurrent);
            vp.setPen(QPen(QColor(Theme::PRIMARY), 1, Qt::DashLine));
            vp.setBrush(QColor(22, 119, 255, 26));
            vp.drawRect(box);
        }
        vp.setBrush(Qt::NoBrush);
    }
    vp.end();

    m_imageLabel->setPixmap(m_cachedVisible);

    // 画面换了，浮层背后的模糊底跟着换（只重画那几个小控件，不重画画面）。
    updateOverlayBackdrops();
    ++m_overlayFrames;       // T-010 仪表：这一帧会让 8 个浮层控件各重画一次
    tickOverlayMeter();

    // Cost trace for the D3 acceptance number: only report renders that are
    // actually expensive enough to show up in a UI-stall sample.
    const qint64 renderMs = m_renderTimer.elapsed();
    if (renderMs >= 30) {
        RuntimeLog::log("[UI] Image2DView::render %lld ms (canvas %dx%d, smooth=%d, preview=%d)",
                        renderMs, cw, ch, m_smoothRender ? 1 : 0, m_livePreview ? 1 : 0);
    }
}

void Image2DView::fitZoom()
{
    if (m_originalPixmap.isNull()) return;
    int vw = m_imageLabel->width();
    int vh = m_imageLabel->height();
    if (vw <= 0 || vh <= 0) return;

    double zw = static_cast<double>(vw) / m_originalPixmap.width();
    double zh = static_cast<double>(vh) / m_originalPixmap.height();
    m_zoomLevel = std::min(zw, zh);
    m_autoFit = true;
    m_canvasDirty = true;
    m_offsetX = 0;
    m_offsetY = 0;

    int cw = static_cast<int>(m_originalPixmap.width() * m_zoomLevel);
    int ch = static_cast<int>(m_originalPixmap.height() * m_zoomLevel);
    m_offsetX = (vw - cw) / 2;
    m_offsetY = (vh - ch) / 2;

    m_zoomLabel->setText(QStringLiteral("适应"));
}

// ── Mouse events ──

void Image2DView::wheelEvent(QWheelEvent* event)
{
    if (m_originalPixmap.isNull()) return;

    double factor = (event->angleDelta().y() > 0) ? 1.15 : 1.0 / 1.15;
    m_zoomLevel *= factor;
    m_zoomLevel = std::clamp(m_zoomLevel, 0.25, 4.0);
    m_autoFit = false;
    m_canvasDirty = true;
    m_smoothRender = false;
    m_smoothTimer->start();

    // Zoom toward mouse position
    QPoint mp = m_imageLabel->mapFrom(this, event->pos());
    int cw = static_cast<int>(m_originalPixmap.width() * m_zoomLevel);
    int ch = static_cast<int>(m_originalPixmap.height() * m_zoomLevel);
    m_offsetX = static_cast<int>(mp.x() - (mp.x() - m_offsetX) * factor);
    m_offsetY = static_cast<int>(mp.y() - (mp.y() - m_offsetY) * factor);

    m_zoomLabel->setText(QStringLiteral("%1%").arg(static_cast<int>(m_zoomLevel * 100)));
    render();
}

void Image2DView::mousePressEvent(QMouseEvent* event)
{
    if (event->button() == Qt::LeftButton) {
        int px = 0, py = 0;
        if (widgetToImagePixel(event->pos(), px, py)) {
            // A click is still a click (pixel picking is unchanged); a drag
            // that follows becomes a ROI selection instead.
            emit pixelClicked(px, py);
            m_roiPending = true;
            m_roiStart = QPoint(px, py);
            m_roiCurrent = QRect();
        }
    } else if (event->button() == Qt::MiddleButton || event->button() == Qt::RightButton) {
        m_panStart = event->pos();
        m_panning = true;
        QApplication::setOverrideCursor(Qt::ClosedHandCursor);
    }
}

void Image2DView::mouseMoveEvent(QMouseEvent* event)
{
    if (m_panning) {
        QPoint delta = event->pos() - m_panStart;
        m_offsetX += delta.x();
        m_offsetY += delta.y();
        m_panStart = event->pos();
        render();
        return;
    }
    if (m_roiPending) {
        int px = 0, py = 0;
        if (!widgetToImagePixelClamped(event->pos(), px, py))
            return;
        const QRect r = QRect(m_roiStart, QPoint(px, py)).normalized();
        if (r == m_roiCurrent)
            return;
        m_roiCurrent = r;
        // Only the visible layer changes, so the cached canvas (the expensive
        // part of a render) is reused while dragging.
        render();
    }
}

void Image2DView::mouseReleaseEvent(QMouseEvent* event)
{
    if (m_panning) {
        m_panning = false;
        QApplication::restoreOverrideCursor();
    }
    if (event->button() == Qt::LeftButton && m_roiPending) {
        m_roiPending = false;
        const QRect r = m_roiCurrent;
        m_roiCurrent = QRect();
        if (r.width() >= kRoiMinDrag && r.height() >= kRoiMinDrag) {
            emit roiSelected(r);
            render();          // the panel answers with setRois(); drop the band
        } else {
            render();
        }
    }
}

void Image2DView::mouseDoubleClickEvent(QMouseEvent* event)
{
    if (event->button() == Qt::LeftButton) {
        fitZoom();
        render();
    }
}

void Image2DView::resizeEvent(QResizeEvent* event)
{
    QWidget::resizeEvent(event);

    // Reposition the overlay labels (kept out of the layout so they float).
    if (m_titleLabel) {
        m_titleLabel->adjustSize();
        m_titleLabel->move(8, 8);
        m_titleLabel->raise();
    }
    if (m_zoomLabel) {
        m_zoomLabel->adjustSize();
        m_zoomLabel->move(width() - m_zoomLabel->width() - 8, 8);
        m_zoomLabel->raise();
    }
    updateToolbarGeometry();
    if (m_pausedHint && m_pausedHint->isVisible()) {
        updatePausedHintGeometry();
        m_pausedHint->raise();
    }

    if (m_autoFit) {
        fitZoom();
    }
    // Live resize uses a fast nearest-neighbor render; a smooth re-render fires
    // 200ms after the resize settles, keeping edge-drag silky.
    m_smoothRender = false;
    m_smoothTimer->start();
    render();
}

bool Image2DView::widgetToImagePixel(const QPoint& pos, int& px, int& py) const
{
    if (m_originalPixmap.isNull() || m_lastZoom <= 0.0)
        return false;
    const QPoint labelPos = m_imageLabel->mapFrom(this, pos);
    const double canvasX = (labelPos.x() - m_lastRenderOx) / m_lastZoom;
    const double canvasY = (labelPos.y() - m_lastRenderOy) / m_lastZoom;
    px = static_cast<int>(std::floor(canvasX));
    py = static_cast<int>(std::floor(canvasY));
    if (px < 0 || py < 0 || px >= m_originalPixmap.width()
            || py >= m_originalPixmap.height())
        return false;
    return true;
}

bool Image2DView::widgetToImagePixelClamped(const QPoint& pos, int& px, int& py) const
{
    if (m_originalPixmap.isNull() || m_lastZoom <= 0.0)
        return false;
    const QPoint labelPos = m_imageLabel->mapFrom(this, pos);
    const double canvasX = (labelPos.x() - m_lastRenderOx) / m_lastZoom;
    const double canvasY = (labelPos.y() - m_lastRenderOy) / m_lastZoom;
    px = std::clamp(static_cast<int>(std::floor(canvasX)), 0, m_originalPixmap.width() - 1);
    py = std::clamp(static_cast<int>(std::floor(canvasY)), 0, m_originalPixmap.height() - 1);
    return true;
}
