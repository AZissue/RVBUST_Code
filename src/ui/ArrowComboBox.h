#pragma once

// The global combo-box QSS strips the native drop-down arrow; repaint a small
// down arrow at the right edge so the drop-down affordance stays visible.
// Shared by the tools panel's pages (it used to live in ToolsPanel.cpp only —
// the per-method measurement pages need exactly the same look).
#include <QComboBox>
#include <QPainter>
#include <QPolygon>
#include <QPaintEvent>

#include "ui/Theme.h"

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
