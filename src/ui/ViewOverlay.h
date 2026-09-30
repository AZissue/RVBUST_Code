#pragma once
// ── 两个视窗共用的浮层（玻璃）组件 ─────────────────────────────────────
// T-003：2D 视窗（Image2DView）与 3D 视窗（VisSceneView）的工具栏按钮此前
// 各画各的底，配色对不上。这里把「浮层控件」抽成一个只写头文件的共享组件：
//
//   * 无描边、无实心底色，QSS 只负责文字与状态色（常态背景 transparent）；
//   * 底是「背后画面的模糊副本」——由宿主通过 setGlassSource() 提供：
//       2D 提供（Image2DView::overlayBlurUnder，抓得到自己画的 pixmap）；
//       3D 提供不了（GL 子窗口背后的像素拿不到，T-001 已证 DWM blur-behind
//         在本机对原生子窗口失效）——**没有源时什么都不画，保持透明**，
//         绝不退化成恒定底色（那正是本轮要消灭的「配色不一样」的根因）。
//
// 圆角常量只有这一处定义（kGlassRadius），与 Theme::viewOverlayButtonStyle() /
// viewOverlayLabelStyle() 里 QSS 的 border-radius 同值（契约冻结：8px）。

#include <QWidget>
#include <QImage>
#include <QPainter>
#include <QPainterPath>
#include <QPushButton>
#include <QLabel>
#include <functional>
#include <utility>

namespace ViewOverlay {

// 浮层的圆角半径：QSS 的 border-radius 与模糊裁剪用的圆角必须同值，否则
// 画出来的形状会差一截。契约冻结：与 Theme 的 viewOverlay*Style() 同为 8。
inline constexpr int kGlassRadius = 8;

// 浮层控件：无描边、无实心底色，底是**背后画面的模糊副本**。
// QSS 只负责文字与状态色（常态背景 transparent），模糊由 paintEvent 在画文字
// 之前铺进控件的圆角形状里；不模糊的地方（按钮外）由父窗口照常画出清晰画面。
template <class Base>
class GlassOverlay : public Base
{
public:
    explicit GlassOverlay(QWidget* parent) : Base(parent) {}
    // 模糊源：给定控件，返回它背后的模糊副本（图像坐标与控件同为 1:1）。
    // 未提供（或返回空图）时控件保持透明——不许退化成恒定底色。
    void setGlassSource(std::function<QImage(const QWidget*)> source)
    {
        m_glassSource = std::move(source);
    }

protected:
    void paintEvent(QPaintEvent* event) override
    {
        if (m_glassSource) {
            const QImage blur = m_glassSource(this);
            if (!blur.isNull()) {
                QPainter p(this);
                p.setRenderHint(QPainter::Antialiasing, true);
                QPainterPath path;
                path.addRoundedRect(QRectF(rect()), kGlassRadius, kGlassRadius);
                p.setClipPath(path);
                // T-002 判据 6「按钮底再透 30%」：模糊底由 100% 不透明改成
                // 70% 合成，剩下 30% 由父窗口那张清晰画面透上来。
                p.setOpacity(0.70);
                p.drawImage(rect(), blur);
                // 文字 / hover / checked 这些 QSS 层仍按原不透明度画。
                p.setOpacity(1.0);
            }
        }
        Base::paintEvent(event);
    }

private:
    std::function<QImage(const QWidget*)> m_glassSource;
};

} // namespace ViewOverlay

using GlassButton = ViewOverlay::GlassOverlay<QPushButton>;
using GlassLabel = ViewOverlay::GlassOverlay<QLabel>;
