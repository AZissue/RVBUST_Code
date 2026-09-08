#include "ui/Image2DView.h"
#include "ui/Theme.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QWheelEvent>
#include <QMouseEvent>
#include <QPainter>
#include <QPen>
#include <QFont>
#include <QApplication>
#include <QTimer>
#include <algorithm>
#include <cmath>

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
}

void Image2DView::updateFrame(const QImage& image, bool preserveView)
{
    if (image.isNull()) return;

    m_originalPixmap = QPixmap::fromImage(image);
    m_canvasDirty = true;

    if (!preserveView) {
        m_autoFit = true;
        m_zoomLevel = 0.0;
        fitZoom();
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
    m_canvasDirty = true;
    m_imageLabel->clear();
}

// ── Rendering (double-buffered Canvas + Visible) ──

void Image2DView::render()
{
    if (m_originalPixmap.isNull()) return;

    int vw = m_imageLabel->width();
    int vh = m_imageLabel->height();
    if (vw <= 0 || vh <= 0) return;

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
    vp.end();

    m_imageLabel->setPixmap(m_cachedVisible);
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
        if (widgetToImagePixel(event->pos(), px, py))
            emit pixelClicked(px, py);
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
    }
}

void Image2DView::mouseReleaseEvent(QMouseEvent* event)
{
    if (m_panning) {
        m_panning = false;
        QApplication::restoreOverrideCursor();
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
