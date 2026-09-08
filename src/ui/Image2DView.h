#pragma once
#include <QWidget>
#include <QLabel>
#include <QPixmap>
#include <QImage>
#include <vector>
#include <tuple>
#include <string>

class Image2DView : public QWidget {
    Q_OBJECT
public:
    explicit Image2DView(QWidget* parent = nullptr);

    void updateFrame(const QImage& image, bool preserveView = false);
    void drawMarkers(const std::vector<std::tuple<float, float, std::string>>& markers);
    void clearMarkers();
    void clear();

signals:
    // Left-click on the image; coordinates are image pixels (0-based).
    void pixelClicked(int x, int y);

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

    QLabel* m_imageLabel;
    QLabel* m_titleLabel;
    QLabel* m_zoomLabel;

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

    bool widgetToImagePixel(const QPoint& pos, int& px, int& py) const;
};
