#pragma once
#include <QWidget>
#include <QLabel>
#include <QPixmap>
#include <QImage>
#include <QElapsedTimer>
#include <QPointer>
#include <QStringList>
#include <QVector>
#include <vector>
#include <tuple>
#include <string>

#include "ui/MeasurementSnapshot.h"

class QPushButton;

// The 2D viewport is also the container for the measurement display pages:
// 图像 | 偏差图 | 尺寸总图 | 截面轮廓 | 重复性趋势.  The pages live inside this
// widget — no extra window — and share its zoom / pan / pick machinery, so
// switching pages never changes how the image behaves.
class Image2DView : public QWidget {
    Q_OBJECT
public:
    enum class Page {
        Image = 0,   // the captured camera image
        Deviation,   // colour map of the signed distance from the fitted plane
        Dimensions,  // leader lines + value call-outs drawn over the image
        Section,     // section profile along the ROI's principal direction
        Repeat       // repeatability run chart + histogram
    };

    explicit Image2DView(QWidget* parent = nullptr);

    void setPage(Page page);
    Page page() const { return m_page; }

    // ROI rectangles in image pixels, drawn over the image (A, B, ...).
    void setRois(const QVector<QRect>& rois, const QStringList& labels);
    void clearRois();

    // Measurement results to paint on the display pages.  Cheap to copy (the
    // heavy members are vectors that are moved in by the caller).
    void setMeasurement(const Measurement::Snapshot& snapshot);

    // `livePreview` marks the streaming preview path (as opposed to a captured
    // still).  Live frames are rendered with a cheap nearest-neighbour scale and
    // the existing 200 ms settle timer then re-renders one smooth frame, so the
    // UI thread never pays for a full-quality scale 20 times a second.
    void updateFrame(const QImage& image, bool preserveView = false,
                     bool livePreview = false);
    void drawMarkers(const std::vector<std::tuple<float, float, std::string>>& markers);
    void clearMarkers();
    void clear();

    // 临时把画面冻结成给定图像（离线工具用）。冻结期间 updateFrame() 仍更新
    // "最后一张真实帧"，但不改屏幕上的画面，也不会丢掉实时数据。
    void setFrozenImage(const QImage& image);
    // 解冻：立刻用最后一张真实帧重绘（没有真实帧时清空画面）。
    void clearFrozenImage();
    bool frozen() const { return m_frozen; }

signals:
    // Left-click on the image; coordinates are image pixels (0-based).
    void pixelClicked(int x, int y);
    // A left-drag finished: the dragged rectangle in image pixels, normalised
    // so width/height are positive.  Only emitted for drags of at least
    // kRoiMinDrag px in both directions (a shorter drag is still a click).
    void roiSelected(const QRect& rect);
    // The toolbar's 清除 ROI button (P3.3): the panel clears its own ROI state
    // and comes back with roisChanged({}, {}), which erases the overlay.
    void roiClearRequested();
    void pageChanged(int page);

protected:
    void wheelEvent(QWheelEvent* event) override;
    void mousePressEvent(QMouseEvent* event) override;
    void mouseMoveEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void mouseDoubleClickEvent(QMouseEvent* event) override;
    void resizeEvent(QResizeEvent* event) override;

private:
    void fitZoom();
    void render();
    void buildPageBar();
    void updatePageBarGeometry();
    // Regenerates m_originalPixmap for the active page.  Cheap no-op when the
    // camera image is unchanged and the page did not move.
    void refreshPagePixmap();
    QPixmap renderDeviationPage(const QSize& size) const;
    QPixmap renderDimensionPage(const QSize& size) const;
    QPixmap renderSectionPage(const QSize& size) const;
    QPixmap renderRepeatPage(const QSize& size) const;

    QLabel* m_imageLabel;
    QLabel* m_titleLabel;
    QLabel* m_zoomLabel;

    // Page machinery (all inside this widget: no extra window).
    QPointer<QWidget> m_pageBar;
    QVector<QPushButton*> m_pageButtons;
    QPointer<QPushButton> m_clearRoiBtn;   // 清除 ROI（工具栏，无 ROI 时禁用）
    Page m_page = Page::Image;
    QImage m_cameraImage;        // last frame, kept for the 尺寸总图 base layer
    // Offline freeze (the 像素→3D tool shows one of its own png on this view).
    // m_cameraImage keeps following the live stream while frozen.
    QImage m_frozenImage;
    bool m_frozen = false;
    Measurement::Snapshot m_snapshot;
    QVector<QRect> m_rois;
    QStringList m_roiLabels;
    QPoint m_roiStart;
    QRect m_roiCurrent;          // rubber band while dragging (image pixels)
    bool m_roiPending = false;   // left button down, may become a drag

    QPixmap m_originalPixmap;
    QPixmap m_cachedCanvas;
    QPixmap m_cachedVisible;
    std::vector<std::tuple<float, float, std::string>> m_markers;

    double m_zoomLevel = 0.0;    // 0 = auto-fit
    double m_lastZoom = 1.0;     // zoom used by the last render()
    bool m_autoFit = true;
    int m_offsetX = 0;
    int m_offsetY = 0;
    int m_lastRenderOx = 0;      // clamped canvas offset used by last render()
    int m_lastRenderOy = 0;
    QPoint m_panStart;
    bool m_panning = false;
    QTimer* m_smoothTimer = nullptr;
    bool m_smoothRender = true;
    bool m_canvasDirty = true;
    bool m_livePreview = false;
    // Render cost trace: logged only when a render actually stalls the UI.
    QElapsedTimer m_renderTimer;

    bool widgetToImagePixel(const QPoint& pos, int& px, int& py) const;
    // Same mapping, but clamped to the image so a drag that leaves the image
    // still produces a usable rectangle.
    bool widgetToImagePixelClamped(const QPoint& pos, int& px, int& py) const;
};
