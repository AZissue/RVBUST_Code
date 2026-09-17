#include "ui/Image2DView.h"
#include "logic/MeasureTools.h"
#include "logic/RuntimeLog.h"
#include "ui/Theme.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QWheelEvent>
#include <QMouseEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPen>
#include <QFont>
#include <QFontMetrics>
#include <QApplication>
#include <QPushButton>
#include <QTimer>
#include <algorithm>
#include <cmath>

namespace {

// A left-drag shorter than this is still a click (pixel picking must keep
// working); the Python tool uses the same 4 px gate for ROI drags.
constexpr int kRoiMinDrag = 4;

// Palette of the Python reference implementation (mviz.py) so the generated
// pages look the same as the tool being matched.
const QColor kPageBg(24, 26, 31);
const QColor kPanelBg(31, 34, 41);
const QColor kGridLine(55, 60, 70);
const QColor kFg(222, 226, 233);
const QColor kDim(140, 148, 162);
const QColor kAccent(255, 167, 38);
const QColor kOk(76, 191, 122);
const QColor kNg(239, 83, 80);
const QColor kLine(90, 170, 245);

QFont pageFont(int px, bool bold = false)
{
    QFont f(QStringLiteral("Microsoft YaHei"), px);
    f.setBold(bold);
    return f;
}

// Deviation colormaps, copied from mviz.py's `colormap()` (t is already
// clamped to [0, 1]).
QRgb devColor(double t, bool coolWarm)
{
    // Shared with the 3D deviation colouring (MeasureTools::cloudDeviationColors)
    // so the two views cannot drift apart.
    const std::array<double, 3> c = MeasureTools::colormap(t, coolWarm);
    return qRgb(static_cast<int>(c[0] * 255.0), static_cast<int>(c[1] * 255.0),
                static_cast<int>(c[2] * 255.0));
}

// Page size before the first capture — the same canvas the Python tool renders
// into (VW x VH = 900 x 660).
QSize fallbackPageSize() { return QSize(900, 660); }

} // namespace

Image2DView::Image2DView(QWidget* parent)
    : QWidget(parent)
{
    setMinimumSize(400, 300);
    setStyleSheet(QStringLiteral("border: 2px solid %1; border-radius: %2px;")
                  .arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS));

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
    m_titleLabel = new QLabel(QStringLiteral("2D 实时图像"), this);
    m_titleLabel->setStyleSheet(QStringLiteral(
        "color: #FFF; background: rgba(0,0,0,0.45); border: none; border-radius: 4px; "
        "padding: 3px 8px; font-size: %1px; font-weight: 600;").arg(Theme::FONT_HINT));
    m_titleLabel->setAttribute(Qt::WA_TransparentForMouseEvents);

    m_zoomLabel = new QLabel(QStringLiteral("适应"), this);
    m_zoomLabel->setStyleSheet(QStringLiteral(
        "color: #FFF; background: rgba(0,0,0,0.45); border: none; border-radius: 4px; "
        "padding: 3px 8px; font-size: %1px;").arg(Theme::FONT_HINT));
    m_zoomLabel->setAttribute(Qt::WA_TransparentForMouseEvents);

    // Zoom-drag uses a fast (nearest-neighbor) scale; a short debounce timer
    // then re-renders the final frame with smooth scaling.
    m_smoothTimer = new QTimer(this);
    m_smoothTimer->setSingleShot(true);
    m_smoothTimer->setInterval(200);
    connect(m_smoothTimer, &QTimer::timeout, this, [this]() {
        m_smoothRender = true;
        render();
    });

    buildPageBar();
}

void Image2DView::updateFrame(const QImage& image, bool preserveView, bool livePreview)
{
    if (image.isNull()) return;

    m_cameraImage = image;

    // A streaming preview must not regenerate a measurement page 20 times a
    // second: on a non-image page the live frames are ignored and the page
    // keeps the last captured measurement.  A captured still always refreshes.
    if (m_page != Page::Image && livePreview) {
        m_canvasDirty = true;
        return;
    }
    if (m_page != Page::Image) {
        refreshPagePixmap();
    } else {
        // convertFromImage reuses the existing pixmap's storage when the size and
        // format still match, so a streaming preview no longer reallocates a
        // 1.5 MP pixmap 20 times a second.
        if (m_originalPixmap.isNull() || m_originalPixmap.size() != image.size())
            m_originalPixmap = QPixmap::fromImage(image);
        else
            m_originalPixmap.convertFromImage(image);
    }
    m_canvasDirty = true;

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
}

// ── Display pages (inside this widget, no extra window) ───────────────

void Image2DView::buildPageBar()
{
    auto* bar = new QWidget(this);
    bar->setObjectName(QStringLiteral("view2d_page_bar"));
    auto* row = new QHBoxLayout(bar);
    row->setContentsMargins(0, 0, 0, 0);
    row->setSpacing(4);

    const QStringList names = { QStringLiteral("图像"), QStringLiteral("偏差图"),
                                QStringLiteral("尺寸总图"), QStringLiteral("截面轮廓"),
                                QStringLiteral("重复性趋势") };
    const QString style = QStringLiteral(
        "QPushButton { color: #E6EAF2; background: rgba(24,26,31,0.72);"
        " border: 1px solid %1; border-radius: 4px; padding: 3px 9px; font-size: %2px; }"
        "QPushButton:hover { background: rgba(22,119,255,0.35); }"
        "QPushButton:checked { background: %3; border-color: %3; color: #FFFFFF;"
        " font-weight: 600; }")
        .arg(Theme::BORDER_DEFAULT).arg(Theme::FONT_HINT).arg(Theme::PRIMARY);

    for (int i = 0; i < names.size(); ++i) {
        auto* btn = new QPushButton(names[i], bar);
        btn->setCheckable(true);
        btn->setAutoExclusive(true);
        btn->setChecked(i == 0);
        btn->setStyleSheet(style);
        btn->setCursor(Qt::PointingHandCursor);
        btn->setFocusPolicy(Qt::NoFocus);
        connect(btn, &QPushButton::clicked, this, [this, i]() { setPage(static_cast<Page>(i)); });
        row->addWidget(btn);
        m_pageButtons.push_back(btn);
    }
    bar->adjustSize();
    bar->raise();
    m_pageBar = bar;
    updatePageBarGeometry();
}

void Image2DView::updatePageBarGeometry()
{
    if (!m_pageBar)
        return;
    m_pageBar->adjustSize();
    m_pageBar->move(8, std::max(8, height() - m_pageBar->height() - 8));
    m_pageBar->raise();
}

void Image2DView::setPage(Page page)
{
    if (m_page == page)
        return;
    m_page = page;
    if (m_pageButtons.size() > static_cast<int>(page)) {
        // setChecked() on an auto-exclusive button clears its siblings.
        if (!m_pageButtons[static_cast<int>(page)]->isChecked())
            m_pageButtons[static_cast<int>(page)]->setChecked(true);
    }
    // The page pixmap has the same size as the camera image, so the current
    // zoom / pan stay valid — switching pages never jumps the view.
    refreshPagePixmap();
    m_canvasDirty = true;
    render();
    emit pageChanged(static_cast<int>(page));
}

void Image2DView::setRois(const QVector<QRect>& rois, const QStringList& labels)
{
    m_rois = rois;
    m_roiLabels = labels;
    m_canvasDirty = true;
    render();
}

void Image2DView::clearRois()
{
    m_rois.clear();
    m_roiLabels.clear();
    m_canvasDirty = true;
    render();
}

void Image2DView::setMeasurement(const Measurement::Snapshot& snapshot)
{
    m_snapshot = snapshot;
    if (m_page != Page::Image) {
        refreshPagePixmap();
        m_canvasDirty = true;
        render();
    }
}

void Image2DView::refreshPagePixmap()
{
    if (m_page == Page::Image) {
        if (!m_cameraImage.isNull()) {
            if (m_originalPixmap.isNull() || m_originalPixmap.size() != m_cameraImage.size())
                m_originalPixmap = QPixmap::fromImage(m_cameraImage);
            else
                m_originalPixmap.convertFromImage(m_cameraImage);
        }
        return;
    }

    const QSize size = m_cameraImage.isNull() ? fallbackPageSize() : m_cameraImage.size();
    QPixmap page;
    switch (m_page) {
    case Page::Deviation:
        page = renderDeviationPage(size);
        break;
    case Page::Dimensions:
        page = renderDimensionPage(size);
        break;
    case Page::Section:
        page = renderSectionPage(size);
        break;
    case Page::Repeat:
        page = renderRepeatPage(size);
        break;
    case Page::Image:
        break;
    }
    if (!page.isNull())
        m_originalPixmap = page;
}

// ── Measurement display pages ──────────────────────────────────────────

// 偏差图: every ROI sample painted where it sits in the image, coloured by its
// signed distance from the fitted plane.  The band is ±3σ_MAD around the
// median (robustLimits) — deliberately not a percentile range, so a single
// flyer at the ROI edge cannot flatten the whole map into one colour.  Samples
// outside the band are pinned to the end colours and counted in the footer.
QPixmap Image2DView::renderDeviationPage(const QSize& size) const
{
    QPixmap pm(size);
    pm.fill(kPageBg);
    QPainter p(&pm);
    p.setRenderHint(QPainter::Antialiasing, true);

    const int W = size.width();
    const int H = size.height();

    if (m_snapshot.devSamples.isEmpty() || m_snapshot.gridW <= 0 || m_snapshot.gridH <= 0) {
        p.setPen(kDim);
        p.setFont(pageFont(16));
        p.drawText(QRect(0, 0, W, H), Qt::AlignCenter, QStringLiteral("数据不足"));
        p.end();
        return pm;
    }

    const double lo = m_snapshot.limitLo;
    const double hi = m_snapshot.limitHi;
    const double span = (hi - lo) > 1e-12 ? (hi - lo) : 1e-12;
    const bool coolWarm = m_snapshot.coolWarm;

    // Same margin layout as mviz.heatmap(): colour bar on the right.
    const int padL = 46, padR = 96, padT = 40, padB = 40;
    const int aw = std::max(1, W - padL - padR);
    const int ah = std::max(1, H - padT - padB);
    const double sx = static_cast<double>(aw) / m_snapshot.gridW;
    const double sy = static_cast<double>(ah) / m_snapshot.gridH;

    // The samples go into an ARGB layer (QPixmap has no setPixel) which is then
    // blitted once, so the per-sample cost stays a pixel write.
    QImage layer(W, H, QImage::Format_ARGB32);
    layer.fill(Qt::transparent);
    for (const Measurement::DevSample& s : m_snapshot.devSamples) {
        const double t = std::min(1.0, std::max(0.0, (s.value - lo) / span));
        const QRgb rgb = devColor(t, coolWarm);
        const int cx = padL + static_cast<int>(s.gx * sx);
        const int cy = padT + static_cast<int>(s.gy * sy);
        // 2x2 splat: a single pixel would leave holes in a sparse ROI.
        for (int dx = 0; dx < 2; ++dx) {
            for (int dy = 0; dy < 2; ++dy) {
                const int x = cx + dx, y = cy + dy;
                if (x >= 0 && x < W && y >= 0 && y < H)
                    layer.setPixel(x, y, rgb);
            }
        }
    }
    p.drawImage(0, 0, layer);

    // Colour bar: hi at the top, lo at the bottom, three signed tick labels.
    const int bx = W - padR + 22, by = padT + 10, bw = 20;
    const int bh = std::max(2, ah - 20);
    for (int i = 0; i < bh; ++i)
        p.fillRect(bx, by + i, bw, 1, devColor(1.0 - static_cast<double>(i) / bh, coolWarm));
    p.setPen(kGridLine);
    p.drawRect(bx, by, bw, bh);
    p.setFont(pageFont(10));
    const double ticks[3] = { hi, 0.5 * (hi + lo), lo };
    for (int i = 0; i < 3; ++i) {
        const int ty = by + static_cast<int>(i * bh / 2.0);
        p.setPen(kDim);
        p.drawText(bx + bw + 5, ty + 4,
                   QStringLiteral("%1").arg(ticks[i], 0, 'f', 3, QLatin1Char(' ')));
    }
    p.setPen(kDim);
    p.drawText(bx, by - 8, m_snapshot.unit.isEmpty() ? QStringLiteral("mm") : m_snapshot.unit);

    p.setPen(kFg);
    p.setFont(pageFont(14, true));
    p.drawText(12, 24, m_snapshot.title.isEmpty() ? QStringLiteral("偏差图") : m_snapshot.title);

    p.setPen(kDim);
    p.setFont(pageFont(10));
    p.drawText(12, H - 22,
               m_snapshot.footer.isEmpty()
                   ? QStringLiteral("色标为稳健区间(±3σ_MAD)，超出的 %1 个点已压到端色")
                         .arg(m_snapshot.clipped)
                   : m_snapshot.footer);
    p.end();
    return pm;
}

// 尺寸总图: the captured image with leader lines and value call-outs.  Labels
// are placed on a fixed radial fan (four quadrants, alternating radius) with a
// leader back to the anchor — deterministic, and it never covers the ROI with
// another label's box.
QPixmap Image2DView::renderDimensionPage(const QSize& size) const
{
    QPixmap pm(size);
    if (m_cameraImage.isNull()) {
        pm.fill(kPageBg);
    } else {
        pm = QPixmap::fromImage(
            m_cameraImage.scaled(size, Qt::IgnoreAspectRatio, Qt::SmoothTransformation));
        // Dim the base so the annotations stay readable over bright pixels.
        QPainter dim(&pm);
        dim.fillRect(QRect(QPoint(0, 0), size), QColor(0, 0, 0, 60));
        dim.end();
    }

    QPainter p(&pm);
    p.setRenderHint(QPainter::Antialiasing, true);
    const int W = size.width(), H = size.height();

    if (m_snapshot.annotations.isEmpty()) {
        p.setPen(kDim);
        p.setFont(pageFont(16));
        p.drawText(QRect(0, 0, W, H), Qt::AlignCenter,
                   QStringLiteral("先执行一次测量，尺寸标注会显示在这里"));
        p.end();
        return pm;
    }

    p.setFont(pageFont(11, true));
    const QFontMetrics fm(p.font());
    for (int i = 0; i < m_snapshot.annotations.size(); ++i) {
        const Measurement::Annotation& a = m_snapshot.annotations[i];
        const QColor col = a.highlight ? kNg : kOk;
        const int tw = fm.horizontalAdvance(a.text);
        const int th = fm.height();
        const int bw = tw + 12, bh = th + 8;

        // Four-quadrant fan, stepping outwards so consecutive labels do not
        // stack on top of each other.
        const int k = i % 4;
        const int radius = 40 + 26 * (i / 4);
        const int dx = (k == 0 || k == 3) ? -radius : radius;
        const int dy = (k < 2) ? -radius : radius;
        QRect box(a.anchor.x() + dx - bw / 2, a.anchor.y() + dy - bh / 2, bw, bh);
        box.moveLeft(std::max(2, std::min(box.left(), W - bw - 2)));
        box.moveTop(std::max(2, std::min(box.top(), H - bh - 2)));

        // Leader line from the box edge to the anchor, with a dot on the anchor.
        const QPoint boxCentre = box.center();
        p.setPen(QPen(col, 1));
        p.drawLine(boxCentre, a.anchor);
        p.setBrush(col);
        p.setPen(Qt::NoPen);
        p.drawEllipse(a.anchor, 3, 3);

        p.setPen(QPen(col, 1));
        p.setBrush(QColor(24, 28, 34, 235));
        p.drawRoundedRect(box, 3, 3);
        p.setPen(kFg);
        p.drawText(box, Qt::AlignCenter, a.text);
    }

    p.setPen(kFg);
    p.setFont(pageFont(14, true));
    p.drawText(12, 24, m_snapshot.title.isEmpty() ? QStringLiteral("尺寸总图") : m_snapshot.title);
    p.setPen(kDim);
    p.setFont(pageFont(10));
    p.drawText(12, H - 22, QStringLiteral("引线指向测量区域 · 单位 mm · 共 %1 项")
                               .arg(m_snapshot.annotations.size()));
    p.end();
    return pm;
}

// 截面轮廓: the binned profile along the ROI's principal direction.
QPixmap Image2DView::renderSectionPage(const QSize& size) const
{
    QPixmap pm(size);
    pm.fill(kPageBg);
    QPainter p(&pm);
    p.setRenderHint(QPainter::Antialiasing, true);
    const int W = size.width(), H = size.height();

    if (m_snapshot.section.size() < 2) {
        p.setPen(kDim);
        p.setFont(pageFont(16));
        p.drawText(QRect(0, 0, W, H), Qt::AlignCenter, QStringLiteral("无数据"));
        p.end();
        return pm;
    }

    const int pad = 56;
    const int aw = std::max(1, W - 2 * pad), ah = std::max(1, H - 2 * pad);
    double t0 = m_snapshot.section.front()[0], t1 = m_snapshot.section.front()[0];
    double v0 = m_snapshot.section.front()[1], v1 = v0;
    for (const auto& s : m_snapshot.section) {
        t0 = std::min(t0, s[0]);
        t1 = std::max(t1, s[0]);
        v0 = std::min(v0, s[1]);
        v1 = std::max(v1, s[1]);
    }
    if (t1 - t0 < 1e-9) t1 = t0 + 1.0;
    if (v1 - v0 < 1e-9) { v0 -= 0.5; v1 += 0.5; }
    const double m = (v1 - v0) * 0.12;
    v0 -= m;
    v1 += m;

    const double sc = std::min(aw / (t1 - t0), ah / (v1 - v0));
    const double ox = pad + (aw - (t1 - t0) * sc) / 2.0;
    const double oy = pad + (ah - (v1 - v0) * sc) / 2.0;
    auto TX = [&](double t) { return ox + (t - t0) * sc; };
    auto TY = [&](double v) { return oy + (v1 - v) * sc; };

    // Grid + height labels.
    p.setPen(kGridLine);
    p.setFont(pageFont(9));
    for (int k = 0; k <= 4; ++k) {
        const double v = v1 - (v1 - v0) * k / 4.0;
        const double y = TY(v);
        p.setPen(kGridLine);
        p.drawLine(QPointF(ox, y), QPointF(ox + (t1 - t0) * sc, y));
        p.setPen(kDim);
        p.drawText(QPointF(pad - 6, y + 3), QStringLiteral("%1").arg(v, 0, 'f', 3));
    }

    // Profile polyline + sample dots.
    QPainterPath path;
    for (std::size_t i = 0; i < m_snapshot.section.size(); ++i) {
        const QPointF pt(TX(m_snapshot.section[i][0]), TY(m_snapshot.section[i][1]));
        if (i == 0)
            path.moveTo(pt);
        else
            path.lineTo(pt);
    }
    p.setPen(QPen(kLine, 2));
    p.setBrush(Qt::NoBrush);
    p.drawPath(path);
    p.setBrush(kAccent);
    p.setPen(Qt::NoPen);
    for (const auto& s : m_snapshot.section) {
        p.drawEllipse(QPointF(TX(s[0]), TY(s[1])), 2.5, 2.5);
    }

    // Segment call-out: the steepest step between neighbouring bins is marked
    // with two dots and labelled with its run and rise — that pair is what a
    // step-height / 段长 reading is taken from.
    const std::vector<std::array<double, 2>>& sec = m_snapshot.section;
    std::size_t knee = 0;
    double maxStep = -1.0;
    for (std::size_t i = 1; i < sec.size(); ++i) {
        const double d = std::fabs(sec[i][1] - sec[i - 1][1]);
        if (d > maxStep) {
            maxStep = d;
            knee = i;
        }
    }
    if (knee > 0) {
        const QPointF a(TX(sec[knee - 1][0]), TY(sec[knee - 1][1]));
        const QPointF b(TX(sec[knee][0]), TY(sec[knee][1]));
        p.setBrush(Qt::NoBrush);
        p.setPen(QPen(kAccent, 1, Qt::DashLine));
        p.drawLine(a, b);
        p.setPen(QPen(kAccent, 1));
        p.drawEllipse(a, 4, 4);
        p.drawEllipse(b, 4, 4);
        const QString txt = QStringLiteral("段长 %1 mm · Δh %2 mm")
                                .arg(sec[knee][0] - sec[knee - 1][0], 0, 'f', 3)
                                .arg(maxStep, 0, 'f', 3);
        p.setFont(pageFont(10, true));
        const QFontMetrics sfm(p.font());
        const int tw = sfm.horizontalAdvance(txt) + 10;
        QRect tb(static_cast<int>((a.x() + b.x()) / 2) - tw / 2,
                 static_cast<int>((a.y() + b.y()) / 2) - 26, tw, sfm.height() + 6);
        tb.moveLeft(std::max(2, std::min(tb.left(), W - tw - 2)));
        tb.moveTop(std::max(2, std::min(tb.top(), H - tb.height() - 2)));
        p.setBrush(QColor(24, 28, 34, 235));
        p.setPen(QPen(kAccent, 1));
        p.drawRoundedRect(tb, 3, 3);
        p.setPen(kFg);
        p.drawText(tb, Qt::AlignCenter, txt);
    }

    p.setPen(kFg);
    p.setFont(pageFont(14, true));
    p.drawText(12, 24, QStringLiteral("截面轮廓"));
    p.setPen(kDim);
    p.setFont(pageFont(10));
    p.drawText(12, H - 22,
               QStringLiteral("沿 ROI 主方向 · 跨度 %1 mm · 分箱 %2 mm · %3 个采样 · 单位 mm")
                   .arg(sec.back()[0] - sec.front()[0], 0, 'f', 3)
                   .arg(m_snapshot.sectionStep, 0, 'f', 3)
                   .arg(m_snapshot.sectionPoints));
    // Axis titles.
    p.drawText(pad, H - 40, QStringLiteral("截面方向 (mm)"));
    p.drawText(pad, pad - 10, QStringLiteral("高度 (mm)"));
    p.end();
    return pm;
}

// 重复性趋势: run chart on top, histogram underneath — the Python tool's
// composition (900x340 chart at y=10, 450x280 histogram below it).
QPixmap Image2DView::renderRepeatPage(const QSize& size) const
{
    QPixmap pm(size);
    pm.fill(kPanelBg);
    QPainter p(&pm);
    p.setRenderHint(QPainter::Antialiasing, true);
    const int W = size.width(), H = size.height();

    if (m_snapshot.series.size() < 1) {
        p.setPen(kDim);
        p.setFont(pageFont(16));
        p.drawText(QRect(0, 0, W, H), Qt::AlignCenter,
                   QStringLiteral("无有效数据（先测量并「加入重复性」）"));
        p.end();
        return pm;
    }

    const QVector<double>& v = m_snapshot.series;
    const double mean = m_snapshot.seriesMean;
    const double stdDev = m_snapshot.seriesSigma;
    const double lo = m_snapshot.hasTolerance ? m_snapshot.tolLo : 0.0;
    const double hi = m_snapshot.hasTolerance ? m_snapshot.tolHi : 0.0;
    const bool hasTol = m_snapshot.hasTolerance;

    // ── run chart ──
    const int chartH = std::min(H - 60, std::max(180, H * 52 / 100));
    const int padL = 78, padR = 22, padT = 38, padB = 34;
    const int aw = std::max(1, W - padL - padR), ah = std::max(1, chartH - padT - padB);
    double y0 = v[0], y1 = v[0];
    for (double x : v) {
        y0 = std::min(y0, x);
        y1 = std::max(y1, x);
    }
    y0 = std::min(y0, mean - 3.0 * stdDev);
    y1 = std::max(y1, mean + 3.0 * stdDev);
    if (hasTol) {
        y0 = std::min(y0, lo);
        y1 = std::max(y1, hi);
    }
    if (y1 - y0 < 1e-9) { y0 -= 1e-3; y1 += 1e-3; }
    const double pad = (y1 - y0) * 0.12;
    y0 -= pad;
    y1 += pad;
    auto Y = [&](double val) { return padT + ah - (val - y0) / (y1 - y0) * ah; };
    auto X = [&](int i) { return padL + (v.size() > 1
                                              ? i * aw / static_cast<double>(v.size() - 1)
                                              : 0.0); };

    p.setFont(pageFont(9));
    for (int k = 0; k <= 4; ++k) {
        const double val = y1 - (y1 - y0) * k / 4.0;
        const double y = padT + ah * k / 4.0;
        p.setPen(kGridLine);
        p.drawLine(QPointF(padL, y), QPointF(padL + aw, y));
        p.setPen(kDim);
        p.drawText(QPointF(padL - 6, y + 3), QStringLiteral("%1").arg(val, 0, 'f', 4));
    }

    auto hLine = [&](double val, const QColor& col, const QString& name, bool rightEnd) {
        if (val < y0 || val > y1)
            return;
        const double y = Y(val);
        p.setPen(QPen(col, 1));
        p.drawLine(QPointF(padL, y), QPointF(padL + aw, y));
        p.setPen(col);
        p.drawText(rightEnd ? QPointF(padL + aw - 2, y - 4) : QPointF(padL + 2, y - 4), name);
    };
    hLine(mean, kDim, QStringLiteral("均值"), true);
    hLine(mean + 3.0 * stdDev, kAccent, QStringLiteral("+3σ"), true);
    hLine(mean - 3.0 * stdDev, kAccent, QStringLiteral("-3σ"), true);
    if (hasTol) {
        // Tolerance lines are dashed (4 px on / 4 px off) in the warning colour.
        for (double val : { lo, hi }) {
            if (val < y0 || val > y1)
                continue;
            const double y = Y(val);
            p.setPen(kNg);
            for (double x = padL; x < padL + aw; x += 8.0)
                p.drawLine(QPointF(x, y), QPointF(std::min(x + 4.0, padL + aw * 1.0), y));
            p.drawText(QPointF(padL + 2, y - 4), val == lo ? QStringLiteral("下限")
                                                           : QStringLiteral("上限"));
        }
    }

    p.setBrush(Qt::NoBrush);
    if (v.size() > 1) {
        QPainterPath path;
        for (int i = 0; i < v.size(); ++i) {
            const QPointF pt(X(i), Y(v[i]));
            if (i == 0)
                path.moveTo(pt);
            else
                path.lineTo(pt);
        }
        p.setPen(QPen(kLine, 2));
        p.drawPath(path);
    }
    for (int i = 0; i < v.size(); ++i) {
        const bool bad = hasTol && (v[i] < lo || v[i] > hi);
        p.setPen(Qt::NoPen);
        p.setBrush(bad ? kNg : kLine);
        p.drawEllipse(QPointF(X(i), Y(v[i])), 3.0, 3.0);
    }

    p.setPen(kFg);
    p.setFont(pageFont(13, true));
    p.drawText(12, 22, m_snapshot.seriesName.isEmpty() ? QStringLiteral("重复性趋势")
                                                       : m_snapshot.seriesName);
    p.setPen(kDim);
    p.setFont(pageFont(10));
    p.drawText(padL, chartH + 6,
               QStringLiteral("n=%1  均值 %2  σ %3  极差 %4  (mm)")
                   .arg(v.size())
                   .arg(mean, 0, 'f', 4)
                   .arg(stdDev, 0, 'f', 4)
                   .arg(m_snapshot.seriesRange, 0, 'f', 4));

    // ── histogram ──
    const int hW = std::max(240, W / 2), hH = std::max(140, H - chartH - 24);
    const int hx = (W - hW) / 2, hy = chartH + 18;
    p.setPen(kGridLine);
    p.drawRect(hx, hy, hW, hH);
    if (v.size() >= 2) {
        const int bins = std::min(18, std::max(3, v.size() / 2));
        double hv0 = v[0], hv1 = v[0];
        for (double x : v) {
            hv0 = std::min(hv0, x);
            hv1 = std::max(hv1, x);
        }
        if (hv1 - hv0 < 1e-12)
            hv1 = hv0 + 1e-6;
        std::vector<int> counts(bins, 0);
        for (double x : v) {
            int b = static_cast<int>((x - hv0) / (hv1 - hv0) * bins);
            b = std::min(bins - 1, std::max(0, b));
            ++counts[b];
        }
        const int hm = *std::max_element(counts.begin(), counts.end());
        const int hpadL = hx + 42, hpadR = hx + hW - 16;
        const int hpadT = hy + 30, hpadB = hy + hH - 30;
        const double baw = (hpadR - hpadL) / static_cast<double>(bins);
        const double bah = std::max(1, hpadB - hpadT);
        p.setPen(Qt::NoPen);
        p.setBrush(kLine);
        for (int i = 0; i < bins; ++i) {
            const double hh = counts[i] / static_cast<double>(std::max(1, hm)) * bah;
            p.drawRect(QRectF(hpadL + i * baw + 1, hpadB - hh, std::max(1.0, baw - 2), hh));
        }
        p.setPen(kGridLine);
        p.drawLine(QPointF(hpadL, hpadB), QPointF(hpadR, hpadB));
        p.setPen(kDim);
        p.setFont(pageFont(9));
        p.drawText(hpadL, hy + hH - 10, QStringLiteral("%1").arg(hv0, 0, 'f', 4));
        p.drawText(hpadR - 60, hy + hH - 10, QStringLiteral("%1 mm").arg(hv1, 0, 'f', 4));
    }
    p.setPen(kFg);
    p.setFont(pageFont(13, true));
    p.drawText(hx + 12, hy + 22, QStringLiteral("分布"));
    p.end();
    return pm;
}

// ── Rendering (double-buffered Canvas + Visible) ──

void Image2DView::render()
{
    if (m_originalPixmap.isNull()) return;

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
    updatePageBarGeometry();

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
