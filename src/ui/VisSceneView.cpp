#include "ui/VisSceneView.h"
#include "ui/Theme.h"

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QApplication>
#include <QWindow>
#include <QMoveEvent>
#include <QTimer>
#include <QPainter>
#include <QFont>
#include <QPaintEvent>
#include <atomic>
#include <mutex>
#include <algorithm>
#include <cmath>
#include <QtConcurrent/QtConcurrentRun>
#include "logic/PointCloudUtils.h"
#include "logic/RuntimeLog.h"

// Light-weight hover label: transparent background, white text with a black
// outline, so it stays readable over any scene content — no tooltip window,
// no box, and no per-frame native window churn.
class HoverTipLabel : public QLabel {
public:
    explicit HoverTipLabel(QWidget* parent = nullptr)
        : QLabel(parent)
    {
        setAttribute(Qt::WA_TransparentForMouseEvents);
        setAttribute(Qt::WA_ShowWithoutActivating);
        setStyleSheet(QStringLiteral("background: transparent; border: none;"));
        setFont(QFont(QStringLiteral("Microsoft YaHei"), 9));
        hide();
    }

protected:
    void paintEvent(QPaintEvent*) override
    {
        QPainter p(this);
        p.setRenderHint(QPainter::TextAntialiasing);
        const QRect r = rect();
        // Black outline first (1px in all 8 directions), then the white text.
        p.setPen(QColor(0, 0, 0, 220));
        for (int dx = -1; dx <= 1; ++dx) {
            for (int dy = -1; dy <= 1; ++dy) {
                if (dx == 0 && dy == 0) continue;
                p.drawText(r.translated(dx, dy),
                           Qt::AlignLeft | Qt::AlignVCenter, text());
            }
        }
        p.setPen(Qt::white);
        p.drawText(r, Qt::AlignLeft | Qt::AlignVCenter, text());
    }
};

// ── PIMPL: Vis-specific code isolated behind HAS_RVBUST_VIS ──

#ifdef HAS_RVBUST_VIS
#include <Vis/Vis.h>
#include <windows.h>
#include <unordered_map>
#include <cstring>

struct VisSceneViewImpl {
    std::unique_ptr<Vis::View> view;
    std::mutex viewMtx;          // protects `view` from being reset while a
                                 // worker-thread pick query is reading it
    HWND visHwnd = nullptr;
    std::string uniqueTitle;
    bool initialized = false;

    // Handle tracking: our int → Vis::Handle and reverse
    int nextHandle = 1;
    std::unordered_map<int, Vis::Handle> objectMap;
    std::unordered_map<Vis::Handle, int, Vis::HandleHasher> reverseMap;

    // Scene state
    Vis::Handle pointCloudHandle;
    Vis::Handle groundHandle;
    Vis::Handle axesHandle;
    std::vector<Vis::Handle> highlightHandles;

    // WNDPROC hook — embedded to avoid heap allocation/deletion race
    struct WndProcCtx {
        WNDPROC oldProc = nullptr;
        double zoomDepth = 0.0;      // local depth estimate for wheel scaling
                                     // (pure math — no Vis calls that could
                                     // block the UI thread)
        DWORD lastWheelTime = 0;
        QWidget* host = nullptr;     // VisSceneView (GUI thread), for queued pick events
        bool mouseDown = false;      // left button click-vs-drag tracking
        int downX = 0;
        int downY = 0;
        bool trackingLeave = false;
        std::atomic<bool> hoverFeedArmed{false};  // pick mode + markers present
        DWORD lastHoverPost = 0;                  // throttle cross-thread posts
    } wndProcCtx;


    // Helpers
    int trackHandle(Vis::Handle vh);
    void releaseHandle(int h);
    void clearHighlights();
    void ensureGround();
    void ensureAxes();
};

int VisSceneViewImpl::trackHandle(Vis::Handle vh) {
    if (vh.type == 0 && vh.uid == 0) return -1;
    int h = nextHandle++;
    objectMap[h] = vh;
    reverseMap[vh] = h;
    return h;
}

void VisSceneViewImpl::releaseHandle(int h) {
    if (!view) return;
    auto it = objectMap.find(h);
    if (it != objectMap.end()) {
        view->Delete(it->second);
        reverseMap.erase(it->second);
        objectMap.erase(it);
    }
}

void VisSceneViewImpl::clearHighlights() {
    if (!view) return;
    for (auto& vh : highlightHandles)
        view->Delete(vh);
    highlightHandles.clear();
}

void VisSceneViewImpl::ensureGround() {
    if (!view) return;
    if (groundHandle.type != 0 || groundHandle.uid != 0) return;
    groundHandle = view->Ground(30, 10.0f, {0.25f, 0.25f, 0.25f});
}

void VisSceneViewImpl::ensureAxes() {
    if (!view) return;
    if (axesHandle.type != 0 || axesHandle.uid != 0) return;
    axesHandle = view->Axes({0, 0, 0}, {0, 0, 0, 1}, 50.0f, 5.0f);
}

// ── HWND finding for Vis window ──

struct FindContext {
    const wchar_t* title;
    HWND result;
};

static BOOL CALLBACK enumWindowsProc(HWND hwnd, LPARAM lParam) {
    auto* ctx = reinterpret_cast<FindContext*>(lParam);
    wchar_t buf[256];
    if (GetWindowTextW(hwnd, buf, 256) > 0 && wcscmp(buf, ctx->title) == 0) {
        LONG_PTR style = GetWindowLongPtrW(hwnd, GWL_STYLE);
        if (!(style & WS_CHILD)) {
            ctx->result = hwnd;
            return FALSE;
        }
    }
    return TRUE;
}

static HWND findVisWindow(const char* title) {
    int len = MultiByteToWideChar(CP_UTF8, 0, title, -1, nullptr, 0);
    std::wstring wtitle(len, L'\0');
    MultiByteToWideChar(CP_UTF8, 0, title, -1, &wtitle[0], len);

    FindContext ctx = {wtitle.c_str(), nullptr};
    EnumWindows(enumWindowsProc, reinterpret_cast<LPARAM>(&ctx));
    return ctx.result;
}

static HWND findVisWindowWithRetry(const char* title, int maxRetries, int delayMs) {
    for (int i = 0; i < maxRetries; ++i) {
        HWND hwnd = findVisWindow(title);
        if (hwnd) return hwnd;
        Sleep(delayMs);
        QApplication::processEvents();
    }
    return nullptr;
}

// ── Vis view creation ──

static std::unique_ptr<Vis::View> createVisView(const char* title, int w, int h) {
    Vis::ViewConfig cfg;
    cfg.name = title;
    cfg.x = 0;
    cfg.y = 0;
    cfg.width = w > 0 ? w : 800;
    cfg.height = h > 0 ? h : 600;
    cfg.bgcolor = {{0.10f, 0.12f, 0.18f, 1.0f}};
    cfg.use_decoration = false;

    return std::make_unique<Vis::View>(cfg, false);
}

// ── WNDPROC subclass: right-button pan + scroll inversion ──

static LRESULT CALLBACK visSubclassProc(HWND hwnd, UINT uMsg, WPARAM wParam, LPARAM lParam) {
    auto* ctx = reinterpret_cast<VisSceneViewImpl::WndProcCtx*>(
        GetPropW(hwnd, L"VisSceneView_WndProcCtx"));
    if (!ctx) return DefWindowProcW(hwnd, uMsg, wParam, lParam);

    switch (uMsg) {
    // Left click (marker picking) — a press+release with < 6px movement is a
    // click; larger movement is the trackball drag and must not pick.
    case WM_LBUTTONDOWN:
        ctx->mouseDown = true;
        ctx->downX = static_cast<short>(LOWORD(lParam));
        ctx->downY = static_cast<short>(HIWORD(lParam));
        if (ctx->host) {
            QMetaObject::invokeMethod(ctx->host, [host = ctx->host]() {
                static_cast<VisSceneView*>(host)->onVisMousePress();
            }, Qt::QueuedConnection);
        }
        break;
    case WM_LBUTTONUP:
        if (ctx->mouseDown) {
            ctx->mouseDown = false;
            const int x = static_cast<short>(LOWORD(lParam));
            const int y = static_cast<short>(HIWORD(lParam));
            const int dx = x - ctx->downX;
            const int dy = y - ctx->downY;
            if (dx * dx + dy * dy <= 36 && ctx->host) {
                QMetaObject::invokeMethod(ctx->host, [host = ctx->host, x, y]() {
                    static_cast<VisSceneView*>(host)->onVisMouseClick(x, y);
                }, Qt::QueuedConnection);
            }
        }
        break;
    case WM_MOUSELEAVE:
        ctx->trackingLeave = false;
        if (ctx->host) {
            QMetaObject::invokeMethod(ctx->host, [host = ctx->host]() {
                static_cast<VisSceneView*>(host)->onVisMouseLeave();
            }, Qt::QueuedConnection);
        }
        break;
    // Right button → middle button (pan)
    case WM_RBUTTONDOWN:
        return CallWindowProcW(ctx->oldProc, hwnd, WM_MBUTTONDOWN,
                               (wParam & ~MK_RBUTTON) | MK_MBUTTON, lParam);
    case WM_RBUTTONUP:
        return CallWindowProcW(ctx->oldProc, hwnd, WM_MBUTTONUP,
                               (wParam & ~MK_RBUTTON) | MK_MBUTTON, lParam);
    case WM_RBUTTONDBLCLK:
        return CallWindowProcW(ctx->oldProc, hwnd, WM_MBUTTONDBLCLK,
                               (wParam & ~MK_RBUTTON) | MK_MBUTTON, lParam);
    // Scroll inversion (delta is in HIWORD) + zoom amplification.  The OSG
    // manipulator moves the camera proportionally to its distance, so zoom
    // feels slower the closer you get.  We track a decaying zoom heuristic
    // (no SDK calls — those block the UI) and amplify the scroll while the
    // user keeps zooming in, so deep zoom stays responsive.
    case WM_MOUSEWHEEL: {
        const short delta = GET_WHEEL_DELTA_WPARAM(wParam);
        const DWORD now = GetTickCount();
        const double dt = (ctx->lastWheelTime ? (now - ctx->lastWheelTime) / 1000.0 : 0.0);
        ctx->lastWheelTime = now;
        // Depth-adaptive zoom: every wheel notch moves the camera by ~10% of
        // its distance to the target (OSG multiplies _distance by 0.9), so at
        // high zoom each notch covers almost no ground.  We keep a slow-
        // decaying local estimate of how deep the user has zoomed and scale
        // the wheel delta up quadratically with depth (1x .. 30x), so deep
        // zoom stays responsive.  Zooming out just resets the estimate.
        ctx->zoomDepth = ctx->zoomDepth * std::exp(-dt / 8.0)
                       + (delta > 0 ? 1.0 : -1.0);
        const double depth = ctx->zoomDepth > 0.0 ? ctx->zoomDepth : 0.0;
        const double amplify = std::clamp(
            1.0 + 0.5 * depth + 0.02 * depth * depth, 1.0, 30.0);
        const double scaled = static_cast<double>(delta) * amplify;
        const short newDelta = static_cast<short>(
            std::clamp(scaled, -30000.0, 30000.0));
        WPARAM newWp = (wParam & 0x0000FFFF) | ((DWORD)(WORD)(-newDelta) << 16);
        return CallWindowProcW(ctx->oldProc, hwnd, uMsg, newWp, lParam);
    }
    // Mouse move: remap MK_RBUTTON → MK_MBUTTON for drag
    case WM_MOUSEMOVE: {
        WPARAM newWp = wParam;
        if (newWp & MK_RBUTTON)
            newWp = (newWp & ~MK_RBUTTON) | MK_MBUTTON;
        // Hover feed for marker picking: only when no button is held (drag
        // rotation must not trigger tooltips).  The render thread's hover
        // intersector is NOT used here — we project markers ourselves on the
        // GUI thread, so no visual artifacts and no per-move SDK round-trips.
        if (!(wParam & (MK_LBUTTON | MK_RBUTTON | MK_MBUTTON))
                && ctx->host && ctx->hoverFeedArmed.load()) {
            if (!ctx->trackingLeave) {
                TRACKMOUSEEVENT tme{sizeof(TRACKMOUSEEVENT), TME_LEAVE, hwnd, 0};
                TrackMouseEvent(&tme);
                ctx->trackingLeave = true;
            }
            // Throttle: even in pick mode, at most one cross-thread hover
            // event per 60ms — the 250ms idle debounce decides whether the
            // tooltip actually appears.
            const DWORD now = GetTickCount();
            if (now - ctx->lastHoverPost >= 60) {
                ctx->lastHoverPost = now;
                QMetaObject::invokeMethod(ctx->host, [host = ctx->host]() {
                    static_cast<VisSceneView*>(host)->onVisMouseMoved();
                }, Qt::QueuedConnection);
            }
        }
        return CallWindowProcW(ctx->oldProc, hwnd, uMsg, newWp, lParam);
    }
    }
    return CallWindowProcW(ctx->oldProc, hwnd, uMsg, wParam, lParam);
}

static void installWndProcHook(HWND hwnd, VisSceneViewImpl& d) {
    SetPropW(hwnd, L"VisSceneView_WndProcCtx", &d.wndProcCtx);
    d.wndProcCtx.oldProc = reinterpret_cast<WNDPROC>(
        SetWindowLongPtrW(hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(visSubclassProc)));
}

static void removeWndProcHook(HWND hwnd, VisSceneViewImpl& d) {
    if (!d.wndProcCtx.oldProc) return;
    // Restore original WNDPROC first — future messages go to OSG directly
    SetWindowLongPtrW(hwnd, GWLP_WNDPROC,
                      reinterpret_cast<LONG_PTR>(d.wndProcCtx.oldProc));
    // Don't null oldProc — in-flight messages on the OSG render thread
    // may still be inside visSubclassProc and need it.
    // Don't RemovePropW — leave the prop alive so in-flight visSubclassProc
    // calls get a valid (non-null) context.  The prop value points into `d`
    // which outlives the HWND (destroyed after Close).
}

// ── Vis embedding init ──

static bool initVisEmbedding(VisSceneViewImpl& d, QWidget* viewport,
                             QWidget* host) {
    if (d.initialized) return true;
    int w = viewport->width();
    int h = viewport->height();
    if (w <= 0 || h <= 0) return false;

    char titleBuf[64];
    snprintf(titleBuf, sizeof(titleBuf), "HandEye3D_%p", viewport);
    d.uniqueTitle = titleBuf;

    d.view = createVisView(titleBuf, w, h);
    if (!d.view) {
        RuntimeLog::log("3D: Vis::View creation failed (%dx%d)", w, h);
        return false;
    }

    d.visHwnd = findVisWindowWithRetry(titleBuf, 20, 25);
    if (!d.visHwnd) {
        RuntimeLog::log("3D: Vis window not found after retries");
        d.view.reset();
        return false;
    }

    // Embed the Vis window as a native child of the viewport so it behaves
    // exactly like the 2D view (moves/resizes with the window, no floating).
    // NOTE: Close() deadlocks while the window is a WS_CHILD — shutdown()
    // detaches it (SetParent(NULL)) before calling Close().
    SetParent(d.visHwnd, reinterpret_cast<HWND>(viewport->winId()));
    LONG_PTR style = GetWindowLongPtrW(d.visHwnd, GWL_STYLE);
    style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU);
    style |= WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS;
    SetWindowLongPtrW(d.visHwnd, GWL_STYLE, style);
    SetWindowPos(d.visHwnd, HWND_BOTTOM, 0, 0, w, h,
                 SWP_NOACTIVATE | SWP_FRAMECHANGED);
    d.view->WindowShow({{0, 0, w, h}});

    // Install WNDPROC hook for right-pan + scroll inversion
    d.wndProcCtx.host = host;
    installWndProcHook(d.visHwnd, d);

    d.initialized = true;
    RuntimeLog::log("3D: Vis embedded OK (%dx%d)", w, h);
    return true;
}

// Position the embedded Vis child over the whole 3D viewport area.
static void positionVisWindow(VisSceneViewImpl& d, QWidget* viewport)
{
    if (!d.visHwnd || !viewport)
        return;
    SetWindowPos(d.visHwnd, HWND_BOTTOM, 0, 0,
                 viewport->width(), viewport->height(),
                 SWP_NOACTIVATE | SWP_NOZORDER);
}

#endif // HAS_RVBUST_VIS

// ═══════════════════════════════════════════════════════════════
// Constructor / Destructor
// ═══════════════════════════════════════════════════════════════

VisSceneView::VisSceneView(QWidget* parent)
    : QWidget(parent)
{
    setMinimumSize(400, 300);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    setStyleSheet(QStringLiteral("border: 2px solid %1; border-radius: %2px;")
                  .arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS));

    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(0);

    m_containerWidget = new QWidget(this);
    m_containerWidget->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    m_containerWidget->setStyleSheet(QStringLiteral("background-color: rgb(26, 31, 46); "
                                                     "border-radius: %1px;").arg(Theme::BORDER_RADIUS));
    layout->addWidget(m_containerWidget, 1);

    m_viewport = new QWidget(m_containerWidget);
    m_viewport->setAttribute(Qt::WA_NativeWindow, true);
    m_viewport->setAttribute(Qt::WA_DontCreateNativeAncestors, true);
    m_viewport->setStyleSheet(QStringLiteral("background-color: transparent; border: none;"));

    m_placeholder = new QLabel(QStringLiteral("3D 标定场景\n\n未启用 3D 可视化"), m_containerWidget);
    m_placeholder->setAlignment(Qt::AlignCenter);
    m_placeholder->setStyleSheet(QStringLiteral("color: #555; font-size: %1px; border: none;")
                                 .arg(Theme::FONT_H2));

    m_imageOverlay = new QLabel(m_containerWidget);
    m_imageOverlay->setAlignment(Qt::AlignCenter);
    m_imageOverlay->setScaledContents(true);
    m_imageOverlay->setStyleSheet(QStringLiteral("border: none; background-color: transparent;"));
    m_imageOverlay->hide();

    // Title bar
    m_titleBar = new QWidget(m_containerWidget);
    m_titleBar->setFixedHeight(28);
    m_titleBar->setStyleSheet(QStringLiteral("background-color: rgba(245,245,245,0.92); "
                              "border-top-left-radius: %1px; border-top-right-radius: %1px;")
                              .arg(Theme::BORDER_RADIUS));
    auto* titleLayout = new QHBoxLayout(m_titleBar);
    titleLayout->setContentsMargins(12, 0, 8, 0);

    auto* title = new QLabel(QStringLiteral("3D 标定场景"), m_titleBar);
    title->setStyleSheet(QStringLiteral("font-size: %1px; font-weight: 600; color: %2; border: none;")
                         .arg(Theme::FONT_BODY).arg(Theme::TEXT_TITLE));
    titleLayout->addWidget(title);
    titleLayout->addStretch();

    setupToolbar();

    m_hoverTimer = new QTimer(this);
    m_hoverTimer->setSingleShot(true);
    m_hoverTimer->setInterval(250);
    connect(m_hoverTimer, &QTimer::timeout, this, &VisSceneView::onHoverTimeout);

    m_hoverTip = new HoverTipLabel(m_containerWidget);

    m_pickWatcher = new QFutureWatcher<PickResult>(this);
    connect(m_pickWatcher, &QFutureWatcher<PickResult>::finished,
            this, &VisSceneView::onPickQueryFinished);

#ifdef HAS_RVBUST_VIS
    d = std::make_shared<VisSceneViewImpl>();
#endif
}

VisSceneView::~VisSceneView() { shutdown(); }

// ═══════════════════════════════════════════════════════════════
// Toolbar (reset button only)
// ═══════════════════════════════════════════════════════════════

void VisSceneView::setupToolbar()
{
    m_toolbar = new QWidget(m_containerWidget);
    m_toolbar->setFixedHeight(28);
    m_toolbar->setStyleSheet(QStringLiteral("background-color: rgba(0,0,0,0.5); "
                             "border-bottom-left-radius: %1px; border-bottom-right-radius: %1px;")
                             .arg(Theme::BORDER_RADIUS));
    auto* btnLayout = new QHBoxLayout(m_toolbar);
    btnLayout->setContentsMargins(8, 0, 8, 0);
    btnLayout->setSpacing(4);

    auto* btnReset = new QPushButton(QStringLiteral("复位"), this);
    btnReset->setFixedHeight(24);
    btnReset->setToolTip(QStringLiteral("复位到默认视角"));
    btnReset->setStyleSheet(QStringLiteral(R"(
        QPushButton { color: #CCC; background: transparent; border: 1px solid #555;
                      border-radius: 4px; font-size: 12px; padding: 0 8px; }
        QPushButton:hover { border-color: %1; color: %1; }
    )").arg(Theme::PRIMARY));
    QObject::connect(btnReset, SIGNAL(clicked()), this, SLOT(resetViewNoAnim()));
    btnLayout->addWidget(btnReset);

    m_pickHint = new QLabel(QStringLiteral("识别后可点击场景中的点选择填充"), this);
    m_pickHint->setStyleSheet(QStringLiteral(
        "color: %1; background: transparent; border: none; font-size: 11px;")
        .arg(Theme::PRIMARY));
    m_pickHint->hide();
    btnLayout->addWidget(m_pickHint);

    btnLayout->addStretch();
}

// ═══════════════════════════════════════════════════════════════
// Core scene methods
// ═══════════════════════════════════════════════════════════════

void VisSceneView::updatePointCloud(const std::vector<float>& xyz, const std::vector<float>& rgb)
{
#ifdef HAS_RVBUST_VIS
    if (!d) return;
    if (!d->initialized) initVisEmbedding(*d, m_viewport, this);
    if (!d->initialized) return;

    if (d->pointCloudHandle.type != 0 || d->pointCloudHandle.uid != 0) {
        d->view->Delete(d->pointCloudHandle);
        d->pointCloudHandle.Reset();
    }

    size_t numPts = xyz.size() / 3;
    std::vector<float> colors;
    if (rgb.empty()) {
        colors.assign(numPts * 3, 0.8f);
    } else if (rgb.size() >= numPts * 3) {
        colors.assign(rgb.begin(), rgb.begin() + numPts * 3);
    } else {
        // Pad short color array with gray
        colors = rgb;
        colors.resize(numPts * 3, 0.8f);
    }
    const bool firstCloud = (d->pointCloudHandle.type == 0 && d->pointCloudHandle.uid == 0);
    d->pointCloudHandle = d->view->Point(xyz, 2.0f, colors);
    if (firstCloud) {
        d->view->Home();  // frame the cloud so it is visible immediately
        d->wndProcCtx.zoomDepth = 0.0;
    }

    m_placeholder->hide();
    m_imageOverlay->hide();
#else
    (void)xyz; (void)rgb;
#endif
}

void VisSceneView::highlightPoints(const std::vector<std::array<float, 3>>& pts3dMM)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;

    d->clearHighlights();

    for (const auto& pt : pts3dMM) {
        if (std::isnan(pt[0]) || std::isnan(pt[1]) || std::isnan(pt[2]))
            continue;

        Vis::Handle h = d->view->Sphere(pt, 1.0f, {0.0f, 1.0f, 0.0f});
        d->highlightHandles.push_back(h);
    }
#else
    (void)pts3dMM;
#endif
}

// ═══════════════════════════════════════════════════════════════
// Marker picking (识别点选择填充)
// ═══════════════════════════════════════════════════════════════

void VisSceneView::setSelectableMarkers(
    const std::vector<std::array<float, 3>>& pts3dMM,
    const std::vector<int>& indices)
{
    ++m_pickQueryId;   // invalidate any in-flight query result
    m_pickMarkers.clear();
    const size_t n = qMin(pts3dMM.size(), indices.size());
    for (size_t i = 0; i < n; ++i) {
        const auto& p = pts3dMM[i];
        if (std::isnan(p[0]) || std::isnan(p[1]) || std::isnan(p[2]))
            continue;
        PickMarker m;
        m.index = indices[i];
        m.pos = p;
        m_pickMarkers.push_back(m);
    }
    if (m_pickHint)
        m_pickHint->setVisible(m_pickEnabled && !m_pickMarkers.empty());
#ifdef HAS_RVBUST_VIS
    if (d)
        d->wndProcCtx.hoverFeedArmed = m_pickEnabled && !m_pickMarkers.empty();
#endif
}

void VisSceneView::setMarkerPickEnabled(bool enabled)
{
    if (m_pickEnabled == enabled)
        return;
    m_pickEnabled = enabled;
    if (!enabled) {
        if (m_hoverTimer) m_hoverTimer->stop();
        if (m_hoverTip) m_hoverTip->hide();
        ++m_pickQueryId;   // invalidate in-flight query results
    }
    if (m_pickHint)
        m_pickHint->setVisible(enabled && !m_pickMarkers.empty());
#ifdef HAS_RVBUST_VIS
    if (d)
        d->wndProcCtx.hoverFeedArmed = enabled && !m_pickMarkers.empty();
#endif
}

void VisSceneView::onVisMouseMoved()
{
    if (!m_pickEnabled || m_pickMarkers.empty() || !m_hoverTimer)
        return;
    m_hoverTimer->start();
}

void VisSceneView::onVisMousePress()
{
    if (m_hoverTimer) m_hoverTimer->stop();
    if (m_hoverTip) m_hoverTip->hide();
}

void VisSceneView::onVisMouseLeave()
{
    if (m_hoverTimer) m_hoverTimer->stop();
    if (m_hoverTip) m_hoverTip->hide();
}

void VisSceneView::onVisMouseClick(int x, int y)
{
    if (m_hoverTimer) m_hoverTimer->stop();
    if (m_hoverTip) m_hoverTip->hide();
    startPickQuery(1, x, y, kClickRadiusPx);
}

void VisSceneView::onHoverTimeout()
{
    if (!m_pickEnabled || m_pickMarkers.empty())
        return;
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized || !d->visHwnd || !IsWindow(d->visHwnd))
        return;
    // Interaction cooldown: right after wheel/button activity the render
    // thread may still be busy — wait for a quiet moment before querying.
    const DWORD now = GetTickCount();
    if (now - d->wndProcCtx.lastWheelTime < 300) {
        m_hoverTimer->start(200);
        return;
    }
    POINT pt;
    if (!GetCursorPos(&pt))
        return;
    ScreenToClient(d->visHwnd, &pt);
    startPickQuery(0, pt.x, pt.y, kHoverRadiusPx);
#else
    if (m_hoverTip) m_hoverTip->hide();
#endif
}

VisSceneView::PickResult VisSceneView::runPickQuery(
    const std::shared_ptr<VisSceneViewImpl>& impl,
    const std::vector<PickMarker>& markers,
    int mouseX, int mouseY, int radiusPx, float fovDeg)
{
#ifdef HAS_RVBUST_VIS
    PickResult out;
    if (!impl || markers.empty())
        return out;

    // Runs on a worker thread.  The mutex only protects `view` from being
    // reset by shutdown(); Vis commands themselves are internally serialized.
    std::lock_guard<std::mutex> lg(impl->viewMtx);
    if (!impl->view)
        return out;
    std::array<float, 3> eye{}, center{}, up{};
    RuntimeLog::log("3D pick: querying camera pose (markers=%zu, %d,%d)",
                    markers.size(), mouseX, mouseY);
    if (!impl->view->GetCameraPose(eye, center, up))
        return out;
    int w = 0, h = 0;
    if (!impl->view->GetViewSize(w, h) || w <= 0 || h <= 0)
        return out;
    RuntimeLog::log("3D pick: hit-test on %dx%d", w, h);

    const float radius2 = static_cast<float>(radiusPx * radiusPx);
    int best = -1;
    std::array<float, 3> bestPos{};
    float bestDist = radius2;
    for (const auto& m : markers) {
        float sx = 0.f, sy = 0.f;
        if (!PointCloudUtils::projectLookAtToScreen(
                eye, center, up, w, h, fovDeg, m.pos, sx, sy))
            continue;
        const float dx = sx - static_cast<float>(mouseX);
        const float dy = sy - static_cast<float>(mouseY);
        const float dist = dx * dx + dy * dy;
        if (dist < bestDist) {
            bestDist = dist;
            best = m.index;
            bestPos = m.pos;
        }
    }
    out.index = best;
    out.pos = bestPos;
    return out;
#else
    (void)impl; (void)markers; (void)mouseX; (void)mouseY;
    (void)radiusPx; (void)fovDeg;
    return {};
#endif
}

void VisSceneView::startPickQuery(int kind, int x, int y, int radiusPx)
{
    if (!m_pickEnabled || m_pickMarkers.empty())
        return;
    if (m_pickQueryRunning) {
        // A click arriving while a query is in flight must not be lost.
        if (kind == 1) {
            m_pendingClickX = x;
            m_pendingClickY = y;
        }
        return;
    }

    m_pickQueryRunning = true;
    m_activeQueryId = ++m_pickQueryId;
    m_activeQueryKind = kind;
    const auto markers = m_pickMarkers;   // copy for the worker thread
    const auto impl = d;
    m_pickWatcher->setFuture(QtConcurrent::run(
        [impl, markers, x, y, radiusPx]() {
            return runPickQuery(impl, markers, x, y, radiusPx, kPickFovDeg);
        }));
}

void VisSceneView::onPickQueryFinished()
{
    m_pickQueryRunning = false;
    const auto result = m_pickWatcher->result();
    if (m_activeQueryId != m_pickQueryId)
        return;   // stale: markers were cleared / changed while querying

    if (m_activeQueryKind == 0)
        showHoverResult(result);
    else
        handleClickResult(result);

    // A click queued while the query was running.
    if (m_pendingClickX >= 0) {
        const int px = m_pendingClickX;
        const int py = m_pendingClickY;
        m_pendingClickX = m_pendingClickY = -1;
        startPickQuery(1, px, py, kClickRadiusPx);
    }
}

void VisSceneView::showHoverResult(const PickResult& result)
{
    if (!m_hoverTip)
        return;
    if (result.index < 0) {
        m_hoverTip->hide();
        return;
    }
    const auto& pos = result.pos;
    m_hoverTip->setText(
        QStringLiteral("#%1  %2, %3, %4")
            .arg(result.index)
            .arg(pos[0], 0, 'f', 3)
            .arg(pos[1], 0, 'f', 3)
            .arg(pos[2], 0, 'f', 3));
    m_hoverTip->adjustSize();
    QPoint tipPos = m_containerWidget->mapFromGlobal(QCursor::pos())
                  + QPoint(14, 12);
    if (tipPos.x() + m_hoverTip->width() > m_containerWidget->width())
        tipPos.setX(tipPos.x() - 14 - m_hoverTip->width() - 4);
    if (tipPos.y() + m_hoverTip->height() > m_containerWidget->height())
        tipPos.setY(tipPos.y() - 12 - m_hoverTip->height() - 4);
    tipPos.setX(qMax(2, tipPos.x()));
    tipPos.setY(qMax(2, tipPos.y()));
    m_hoverTip->move(tipPos);
    m_hoverTip->raise();
    m_hoverTip->show();
}

void VisSceneView::handleClickResult(const PickResult& result)
{
    if (result.index >= 0)
        emit markerPicked(result.index, result.pos[0], result.pos[1], result.pos[2]);
}

void VisSceneView::clear()
{
    // Qt-side pick state (independent of the Vis backend)
    m_pickMarkers.clear();
    m_pickEnabled = false;
    ++m_pickQueryId;
    if (m_pickHint) m_pickHint->hide();
    if (m_hoverTimer) m_hoverTimer->stop();
    if (m_hoverTip) m_hoverTip->hide();

#ifdef HAS_RVBUST_VIS
    if (d)
        d->wndProcCtx.hoverFeedArmed = false;
    if (!d || !d->initialized) {
        m_placeholder->show();
        return;
    }

    if (d->pointCloudHandle.type != 0 || d->pointCloudHandle.uid != 0) {
        d->view->Delete(d->pointCloudHandle);
        d->pointCloudHandle.Reset();
    }

    d->clearHighlights();

    for (auto& kv : d->objectMap)
        d->view->Delete(kv.second);
    d->objectMap.clear();
    d->reverseMap.clear();
    d->nextHandle = 1;

    d->view->Clear();

    d->groundHandle.Reset();
    d->axesHandle.Reset();
    d->ensureGround();
    d->ensureAxes();

    // Make sure the floating window is visible again (it is hidden while the
    // stereo image overlay is shown).
    if (d->visHwnd) {
        ShowWindow(d->visHwnd, SW_SHOW);
        positionVisWindow(*d, m_viewport);
    }
    m_placeholder->show();
#else
    m_placeholder->show();
#endif
}

// ═══════════════════════════════════════════════════════════════
// Camera presets
// ═══════════════════════════════════════════════════════════════

void VisSceneView::setViewPreset(const QString& name)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;

    if (name == "home") {
        d->view->Home();
    } else if (name == "front") {
        d->view->SetCameraPose({0, 0, 500}, {0, 500, 0}, {0, 0, 1});
    } else if (name == "top") {
        d->view->SetCameraPose({0, 0, 500}, {0, 0, 0}, {0, 1, 0});
    } else if (name == "right") {
        d->view->SetCameraPose({500, 0, 0}, {0, 0, 0}, {0, 0, 1});
    }
#else
    (void)name;
#endif
}

void VisSceneView::resetViewNoAnim() { resetView(false); }

void VisSceneView::resetView(bool animated)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;
    d->wndProcCtx.zoomDepth = 0.0;
    d->view->Home();
#else
    (void)animated;
#endif
}

// ═══════════════════════════════════════════════════════════════
// Scene objects: creation
// ═══════════════════════════════════════════════════════════════

int VisSceneView::addSphere(const std::array<float, 3>& centerMM, float radiusMM,
                             const std::array<float, 3>& color)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return -1;
    Vis::Handle h = d->view->Sphere(centerMM, radiusMM, {color[0], color[1], color[2]});
    return d->trackHandle(h);
#else
    (void)centerMM; (void)radiusMM; (void)color;
    return -1;
#endif
}

int VisSceneView::addBox(const std::array<float, 3>& centerMM,
                          const std::array<float, 3>& halfExtentsMM,
                          const std::array<float, 3>& color)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return -1;
    Vis::Handle h = d->view->Box(centerMM, halfExtentsMM, {color[0], color[1], color[2]});
    return d->trackHandle(h);
#else
    (void)centerMM; (void)halfExtentsMM; (void)color;
    return -1;
#endif
}

int VisSceneView::addCone(const std::array<float, 3>& centerMM, float radiusMM,
                           float heightMM, const std::array<float, 3>& color)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return -1;
    Vis::Handle h = d->view->Cone(centerMM, radiusMM, heightMM, {color[0], color[1], color[2]});
    return d->trackHandle(h);
#else
    (void)centerMM; (void)radiusMM; (void)heightMM; (void)color;
    return -1;
#endif
}

int VisSceneView::addCylinder(const std::array<float, 3>& centerMM, float radiusMM,
                               float heightMM, const std::array<float, 3>& color)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return -1;
    Vis::Handle h = d->view->Cylinder(centerMM, radiusMM, heightMM, {color[0], color[1], color[2]});
    return d->trackHandle(h);
#else
    (void)centerMM; (void)radiusMM; (void)heightMM; (void)color;
    return -1;
#endif
}

int VisSceneView::addArrow(const std::array<float, 3>& tailMM, const std::array<float, 3>& headMM,
                            float radiusMM, const std::array<float, 3>& color)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return -1;
    std::vector<float> tails = {tailMM[0], tailMM[1], tailMM[2]};
    std::vector<float> heads = {headMM[0], headMM[1], headMM[2]};
    Vis::Handle h = d->view->Arrow(tails, heads, radiusMM, {color[0], color[1], color[2]});
    return d->trackHandle(h);
#else
    (void)tailMM; (void)headMM; (void)radiusMM; (void)color;
    return -1;
#endif
}

int VisSceneView::addPlane(float xLenM, float yLenM, int xCells, int yCells,
                            const std::array<float, 3>* posMM,
                            const std::array<float, 4>* quat,
                            const std::array<float, 3>& color)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return -1;
    Vis::Handle h;
    if (posMM && quat) {
        h = d->view->Plane(xLenM, yLenM, xCells, yCells, *posMM, *quat,
                           {color[0], color[1], color[2]});
    } else {
        h = d->view->Plane(xLenM, yLenM, xCells, yCells, {color[0], color[1], color[2]});
    }
    return d->trackHandle(h);
#else
    (void)xLenM; (void)yLenM; (void)xCells; (void)yCells;
    (void)posMM; (void)quat; (void)color;
    return -1;
#endif
}

int VisSceneView::addMesh(const std::vector<float>& vertsM, const std::vector<int>& faces,
                           const std::array<float, 3>& color)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return -1;
    std::vector<unsigned int> indices;
    indices.reserve(faces.size());
    for (int idx : faces) {
        if (idx < 0) continue;
        indices.push_back(static_cast<unsigned int>(idx));
    }
    Vis::Handle h = d->view->Mesh(vertsM, indices, {color[0], color[1], color[2]});
    return d->trackHandle(h);
#else
    (void)vertsM; (void)faces; (void)color;
    return -1;
#endif
}

int VisSceneView::addText(const QString& content, const std::array<float, 3>& posMM,
                           float fontSize, const std::array<float, 3>& color)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return -1;
    std::string text = content.toStdString();
    std::vector<float> pos = {posMM[0], posMM[1], posMM[2]};
    Vis::Handle h = d->view->Text(text, pos, fontSize, {color[0], color[1], color[2]});
    return d->trackHandle(h);
#else
    (void)content; (void)posMM; (void)fontSize; (void)color;
    return -1;
#endif
}

int VisSceneView::addSpheresBatch(const std::vector<float>& centersMMFlat, float radiusMM,
                                   const std::array<float, 3>& color)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return -1;
    size_t n = centersMMFlat.size() / 3;
    if (n == 0) return -1;
    std::vector<float> radii(n, radiusMM);
    Vis::Handle h = d->view->Spheres(centersMMFlat, radii, {color[0], color[1], color[2], 1.0f});
    return d->trackHandle(h);
#else
    (void)centersMMFlat; (void)radiusMM; (void)color;
    return -1;
#endif
}

int VisSceneView::loadModel(const QString& filepath)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return -1;
    Vis::Handle h = d->view->Load(filepath.toStdString());
    return d->trackHandle(h);
#else
    (void)filepath;
    return -1;
#endif
}

// ═══════════════════════════════════════════════════════════════
// Scene objects: manipulation
// ═══════════════════════════════════════════════════════════════

void VisSceneView::removeObject(int handle)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;
    d->releaseHandle(handle);
#else
    (void)handle;
#endif
}

void VisSceneView::setVisible(int handle, bool visible)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;
    auto it = d->objectMap.find(handle);
    if (it == d->objectMap.end()) return;
    if (visible)
        d->view->Show(it->second);
    else
        d->view->Hide(it->second);
#else
    (void)handle; (void)visible;
#endif
}

void VisSceneView::setObjectPosition(int handle, const std::array<float, 3>& posMM)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;
    auto it = d->objectMap.find(handle);
    if (it == d->objectMap.end()) return;
    d->view->SetPosition(it->second, posMM);
#else
    (void)handle; (void)posMM;
#endif
}

void VisSceneView::setObjectRotation(int handle, const std::array<float, 4>& quat)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;
    auto it = d->objectMap.find(handle);
    if (it == d->objectMap.end()) return;
    d->view->SetRotation(it->second, quat);
#else
    (void)handle; (void)quat;
#endif
}

void VisSceneView::setObjectColor(int handle, const std::array<float, 3>& color)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;
    auto it = d->objectMap.find(handle);
    if (it == d->objectMap.end()) return;
    d->view->SetColor(it->second, {color[0], color[1], color[2]});
#else
    (void)handle; (void)color;
#endif
}

void VisSceneView::setObjectTransparency(int handle, float alpha)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;
    auto it = d->objectMap.find(handle);
    if (it == d->objectMap.end()) return;
    d->view->SetTransparency(it->second, 1.0f - alpha);
#else
    (void)handle; (void)alpha;
#endif
}

// ═══════════════════════════════════════════════════════════════
// 2D Image overlay
// ═══════════════════════════════════════════════════════════════

void VisSceneView::showImage(const QImage& img)
{
    m_placeholder->hide();
    m_imageOverlay->setPixmap(QPixmap::fromImage(img.scaled(m_containerWidget->size(),
                              Qt::KeepAspectRatio, Qt::SmoothTransformation)));
    m_imageOverlay->setGeometry(0, 0, m_containerWidget->width(), m_containerWidget->height());
    m_imageOverlay->show();
#ifdef HAS_RVBUST_VIS
    // The floating Vis window would cover the Qt overlay; hide it while the
    // stereo right-camera image is shown.
    if (d && d->initialized && d->visHwnd)
        ShowWindow(d->visHwnd, SW_HIDE);
#endif
}

void VisSceneView::hideImage()
{
    m_imageOverlay->hide();
#ifdef HAS_RVBUST_VIS
    if (d && d->initialized && d->visHwnd && !m_shuttingDown) {
        ShowWindow(d->visHwnd, SW_SHOW);
        positionVisWindow(*d, m_viewport);
    } else {
        m_placeholder->show();
    }
#else
    m_placeholder->show();
#endif
}

// ═══════════════════════════════════════════════════════════════
// Lifecycle
// ═══════════════════════════════════════════════════════════════

void VisSceneView::shutdown()
{
#ifdef HAS_RVBUST_VIS
    if (!d || m_shuttingDown) return;

    // 1. Set shutdown flag FIRST — prevents showEvent/resizeEvent re-entry
    m_shuttingDown = true;
    d->initialized = false;
    d->wndProcCtx.hoverFeedArmed = false;

    // 2. Remove WNDPROC hook before any window operations
    if (d->visHwnd && IsWindow(d->visHwnd)) {
        removeWndProcHook(d->visHwnd, *d);
        // Detach from the Qt parent first: Close() deadlocks on a WS_CHILD
        // window but returns normally on a top-level one.
        SetParent(d->visHwnd, nullptr);
    }

    // 3. Close the Vis view — destroys OSG render thread and the HWND.
    //    After Close(), the HWND is gone, so Qt's later destruction of
    //    m_viewport won't find any child HWND to double-destroy.
    ++m_pickQueryId;   // invalidate in-flight pick queries
    if (d->view) {
        {
            // Wait for any worker-thread pick query to finish before resetting
            // the view pointer.
            std::lock_guard<std::mutex> lg(d->viewMtx);
            if (d->visHwnd && IsWindow(d->visHwnd))
                ShowWindow(d->visHwnd, SW_HIDE);
            d->view->Close();
            d->view.reset();
        }
        RuntimeLog::log("3D: Vis closed");
    }

    // 4. Clear all handle state
    d->objectMap.clear();
    d->reverseMap.clear();
    d->pointCloudHandle.Reset();
    d->groundHandle.Reset();
    d->axesHandle.Reset();
    d->highlightHandles.clear();
    d->visHwnd = nullptr;
#endif
}

// ═══════════════════════════════════════════════════════════════
// Qt Events
// ═══════════════════════════════════════════════════════════════

void VisSceneView::resizeEvent(QResizeEvent* event)
{
    QWidget::resizeEvent(event);
    if (!m_containerWidget) return;

    int cw = m_containerWidget->width();
    int ch = m_containerWidget->height();

    if (m_titleBar)
        m_titleBar->setGeometry(0, 0, cw, m_titleBar->height());
    if (m_toolbar)
        m_toolbar->setGeometry(0, ch - m_toolbar->height(), cw, m_toolbar->height());
    if (m_placeholder)
        m_placeholder->setGeometry(0, 0, cw, ch);
    if (m_imageOverlay)
        m_imageOverlay->setGeometry(0, 0, cw, ch);

    int vpTop = m_titleBar ? m_titleBar->height() : 28;
    int vpBottom = m_toolbar ? m_toolbar->height() : 28;
    int vpH = ch - vpTop - vpBottom;
    if (vpH < 0) vpH = 0;
    if (m_viewport)
        m_viewport->setGeometry(0, vpTop, cw, vpH);

#ifdef HAS_RVBUST_VIS
    if (m_shuttingDown) return;
    if (d && d->initialized && d->visHwnd) {
        d->view->WindowSetRectangle(0, 0, cw, vpH);
        positionVisWindow(*d, m_viewport);
    } else if (d && !d->initialized && vpH > 0) {
        initVisEmbedding(*d, m_viewport, this);
        positionVisWindow(*d, m_viewport);
    }
#endif
}

void VisSceneView::showEvent(QShowEvent* event)
{
    QWidget::showEvent(event);
#ifdef HAS_RVBUST_VIS
    if (m_shuttingDown) return;
    if (d && !d->initialized) {
        int cw = m_containerWidget->width();
        int ch = m_containerWidget->height();
        int vpTop = m_titleBar ? m_titleBar->height() : 28;
        int vpBottom = m_toolbar ? m_toolbar->height() : 28;
        int vpH = ch - vpTop - vpBottom;
        if (vpH > 0 && cw > 0) {
            initVisEmbedding(*d, m_viewport, this);
            positionVisWindow(*d, m_viewport);
        }
    }
#endif
}
