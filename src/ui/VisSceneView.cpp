#include "ui/VisSceneView.h"
#include "ui/Theme.h"
#include "ui/ViewOverlay.h"   // 与 2D 视窗共用的浮层（玻璃）按钮组件（T-003）

#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QApplication>
#include <QWindow>
#include <QMoveEvent>
#include <QTimer>
#include <QPainter>
#include <QFont>
#include <QPaintEvent>
#include <QThread>
#include <atomic>
#include <memory>
#include <mutex>
#include <thread>
#include <algorithm>
#include <cmath>
#include <QtConcurrent/QtConcurrentRun>
#include "logic/PointCloudUtils.h"
#include "logic/RuntimeLog.h"
#include "logic/TransformTools.h"

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
    // Init sentinel.  Embedding spans several steps (create view → wait for its
    // HWND → reparent).  Without this, a re-entrant call made while those steps
    // were still running created a *second* Vis::View (leaked, and both fought
    // over the same HWND title).  Set for the whole span, cleared on success,
    // failure and shutdown.
    bool initializing = false;

    // Handle tracking: our int → Vis::Handle and reverse
    int nextHandle = 1;
    std::unordered_map<int, Vis::Handle> objectMap;
    std::unordered_map<Vis::Handle, int, Vis::HandleHasher> reverseMap;

    // Scene state
    Vis::Handle pointCloudHandle;
    Vis::Handle groundHandle;
    Vis::Handle axesHandle;
    std::vector<Vis::Handle> highlightHandles;

    // Reused padding buffer for updatePointCloud()'s gray/padded colour path.
    // Held here so a repeated upload does not allocate a fresh 8 MB vector and
    // re-touch every element (D3: the colour array used to be rebuilt in full
    // on every call).
    std::vector<float> scratchColors;

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

// Bounded inline poll for a window that the Vis render thread has just
// created.  Deliberately does NOT pump the Qt event loop: a nested
// processEvents() here is what allowed a re-entrant init to create a second
// Vis::View.  The HWND is created by the Vis thread, so sleeping this thread
// does not prevent it from appearing.  If the poll comes up empty the caller
// keeps initializing and retries from a one-shot timer instead of blocking.
static constexpr int kInlineFindAttempts = 8;   // ~16 ms of blocking at most
static constexpr int kInlineFindDelayMs  = 2;
static constexpr int kFindRetryEveryMs   = 20;
static constexpr int kMaxFindRetries     = 25;  // ~0.5 s total budget

// Bounded wait for the worker-thread Vis::View::Close() in shutdown().  The
// call normally returns in a few hundred ms; the bound only exists so a stuck
// Vis render thread cannot keep the process alive after the window is gone.
static constexpr int kViewCloseWaitMs = 3000;

static HWND findVisWindowPolled(const char* title) {
    for (int i = 0; i < kInlineFindAttempts; ++i) {
        HWND hwnd = findVisWindow(title);
        if (hwnd) return hwnd;
        Sleep(kInlineFindDelayMs);
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

// Phase 2: the Vis HWND exists — reparent it into the Qt viewport and finish
// the setup.  Only ever reached with `d->initializing` set, so at most one
// caller can be here at a time.
static bool embedVisWindow(const std::shared_ptr<VisSceneViewImpl>& d,
                           QWidget* viewport, QWidget* host) {
    if (!d->view || !d->visHwnd)
        return false;

    const int w = viewport->width();
    const int h = viewport->height();

    // Embed the Vis window as a native child of the viewport so it behaves
    // exactly like the 2D view (moves/resizes with the window, no floating).
    // NOTE: Close() deadlocks while the window is a WS_CHILD — shutdown()
    // detaches it (SetParent(NULL)) before calling Close().
    SetParent(d->visHwnd, reinterpret_cast<HWND>(viewport->winId()));
    LONG_PTR style = GetWindowLongPtrW(d->visHwnd, GWL_STYLE);
    style &= ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_SYSMENU);
    style |= WS_CHILD | WS_VISIBLE | WS_CLIPCHILDREN | WS_CLIPSIBLINGS;
    SetWindowLongPtrW(d->visHwnd, GWL_STYLE, style);
    SetWindowPos(d->visHwnd, HWND_BOTTOM, 0, 0, w, h,
                 SWP_NOACTIVATE | SWP_FRAMECHANGED);
    d->view->WindowShow({{0, 0, w, h}});

    // Install WNDPROC hook for right-pan + scroll inversion
    d->wndProcCtx.host = host;
    installWndProcHook(d->visHwnd, *d);

    d->initialized = true;
    d->initializing = false;
    RuntimeLog::log("3D: Vis embedded OK (%dx%d)", w, h);
    return true;
}

// One-shot retry driven by the event loop.  The impl is held by shared_ptr and
// the timer is bound to `host`, so the callback can neither outlive the widget
// nor touch a freed impl.  No nested event loop is involved.
static void retryVisFind(const std::shared_ptr<VisSceneViewImpl>& d,
                         QWidget* viewport, QWidget* host, int attempt) {
    QTimer::singleShot(kFindRetryEveryMs, host,
                       [d, viewport, host, attempt]() {
        // shutdown() clears the sentinel; that cancels any pending retry.
        if (!d->initializing)
            return;
        if (!d->view) {
            d->initializing = false;
            return;
        }
        HWND hwnd = findVisWindow(d->uniqueTitle.c_str());
        if (hwnd) {
            d->visHwnd = hwnd;
            embedVisWindow(d, viewport, host);
            return;
        }
        if (attempt + 1 >= kMaxFindRetries) {
            RuntimeLog::log("3D: Vis window not found after %d retries — giving up",
                            kMaxFindRetries);
            d->view.reset();
            d->initializing = false;
            return;
        }
        retryVisFind(d, viewport, host, attempt + 1);
    });
}

// Non-reentrant init.  Returns true only once the window is actually embedded;
// a re-entrant call made while the sentinel is set reports "not ready" instead
// of creating a second Vis::View.
static bool initVisEmbedding(const std::shared_ptr<VisSceneViewImpl>& d,
                             QWidget* viewport, QWidget* host) {
    if (!d) return false;
    if (d->initialized) return true;
    if (d->initializing) return false;   // sentinel: a second View is forbidden

    int w = viewport->width();
    int h = viewport->height();
    if (w <= 0 || h <= 0) return false;

    char titleBuf[64];
    snprintf(titleBuf, sizeof(titleBuf), "HandEye3D_%p", viewport);
    d->uniqueTitle = titleBuf;

    d->initializing = true;
    d->view = createVisView(titleBuf, w, h);
    if (!d->view) {
        RuntimeLog::log("3D: Vis::View creation failed (%dx%d)", w, h);
        d->initializing = false;
        return false;
    }

    // Fast path: the window is usually up by the time the constructor returns.
    d->visHwnd = findVisWindowPolled(titleBuf);
    if (d->visHwnd)
        return embedVisWindow(d, viewport, host);

    // Slow path: keep the sentinel set and retry from the event loop, so the
    // UI is never blocked and no re-entrant init can slip in meanwhile.
    retryVisFind(d, viewport, host, 0);
    return false;
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
// 3D 浮层的「背景模糊」（T-001 判据 3）
//
// 这三个按钮和那条提示是原生窗口（WA_NativeWindow + WA_DontCreateNativeAncestors
// + WA_TranslucentBackground），盖在 OSG 的原生 GL 子窗口上。Qt 侧 grab() 抓不到
// 背后的 GL 画面，所以 2D 那套「把背后像素抓下来自己模糊」在这里不成立。
// 现成可用、又能拿到**真**模糊的通路只剩一条：让桌面窗口管理器在合成时做——
// 给窗口挂 accent 策略 ACCENT_ENABLE_BLURBEHIND，DWM 就会把该窗口背后的内容
// （这里正是 GL 场景）模糊后填进窗口，Qt 侧一个像素都不用画。
//
// 用 GetProcAddress 动态取符号：不新增链接依赖、不引第三方库、也不引 Qt 模块；
// 符号不存在（老系统/被裁剪的 user32）时静默跳过，窗口仍是透明浮层，
// 由 Theme::viewOverlayButtonStyle() 保证没有描边、没有恒定底色。
// ═══════════════════════════════════════════════════════════════
#ifdef Q_OS_WIN
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>

namespace {

// Windows SDK 只给了函数指针类型，这几个结构体是它未公开的配对物。
enum AccentState {
    kAccentDisabled = 0,
    kAccentEnableBlurBehind = 3,
};

struct AccentPolicy {
    int accentState;
    int flags;
    int gradientColor;   // AABBGGRR
    int animationId;
};

// 这个结构体是 SetWindowCompositionAttribute 的参数，Windows SDK 只给了函数指针
// 类型、没导出这个未公开的配对物，所以要自己写。dataSize 是 **SIZE_T**，不是
// unsigned long：LLP64 下 unsigned long 只有 4 字节，SIZE_T 在 x64 是 8 字节。
// 写错的话结构体比 API 期望的少 4 字节，dataSize 后面那 4 字节是编译器填充
// （`{}` 是否清零不保证），调用方一次误读就可能拿到天文数字。
struct WindowCompositionAttributeData {
    int attribute;
    void* data;
    SIZE_T dataSize;
};
static_assert(sizeof(WindowCompositionAttributeData) == 3 * sizeof(void*),
              "WindowCompositionAttributeData 必须与 user32 期望的布局一致");

constexpr int kWindowCompositionAttributeAccentPolicy = 19;

bool setBlurBehind(HWND hwnd)
{
    // 只查一次；user32 一直活着，函数地址不会变。
    static const auto setAttribute =
        reinterpret_cast<BOOL(WINAPI*)(HWND, WindowCompositionAttributeData*)>(
            GetProcAddress(GetModuleHandleW(L"user32.dll"),
                           "SetWindowCompositionAttribute"));
    if (!setAttribute || hwnd == nullptr)
        return false;

    AccentPolicy policy{};
    policy.accentState = kAccentEnableBlurBehind;

    WindowCompositionAttributeData data{};
    data.attribute = kWindowCompositionAttributeAccentPolicy;
    data.data = &policy;
    data.dataSize = sizeof(policy);
    return setAttribute(hwnd, &data) != FALSE;
}

// 给一个浮层控件挂上（或重新挂上）DWM 模糊。winId() 只是把原生窗口做出来，
// 不改动任何 Qt 侧窗口属性——三个按钮的原生属性契约不受影响。
void applyBlurBehind(QWidget* w)
{
    if (!w)
        return;
    if (!setBlurBehind(reinterpret_cast<HWND>(w->winId())))
        RuntimeLog::log("3D: DWM blur-behind not applied to overlay \"%s\"",
                        w->objectName().toUtf8().constData());
}

} // namespace
#else
// 非 Windows：没有 DWM 这条通路，浮层保持"无描边 + 透明底"，
// 裁掉的底色由 Theme 侧保证（不在这里补恒定半透明底）。
static void applyBlurBehind(QWidget*) {}
#endif // Q_OS_WIN

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
    m_containerWidget->setStyleSheet(QStringLiteral("background-color: %1; "
                                                     "border-radius: %2px;")
                                         .arg(Theme::BG_SCENE_3D)
                                         .arg(Theme::BORDER_RADIUS));
    layout->addWidget(m_containerWidget, 1);

    m_viewport = new QWidget(m_containerWidget);
    m_viewport->setAttribute(Qt::WA_NativeWindow, true);
    m_viewport->setAttribute(Qt::WA_DontCreateNativeAncestors, true);
    m_viewport->setStyleSheet(QStringLiteral("background-color: transparent; border: none;"));

    m_placeholder = new QLabel(QStringLiteral("3D 标定场景\n\n未启用 3D 可视化"), m_containerWidget);
    m_placeholder->setAlignment(Qt::AlignCenter);
    // 用户反馈 4：占位文字同样是无边框 + 很淡的半透明底；字号保持原来的 H2。
    m_placeholder->setStyleSheet(Theme::viewOverlayLabelStyle()
                                 + QStringLiteral("QLabel { font-size: %1px; }")
                                       .arg(Theme::FONT_H2));

    m_imageOverlay = new QLabel(m_containerWidget);
    m_imageOverlay->setAlignment(Qt::AlignCenter);
    m_imageOverlay->setScaledContents(true);
    m_imageOverlay->setStyleSheet(QStringLiteral("border: none; background-color: transparent;"));
    m_imageOverlay->hide();

    // No title bar — the "3D 标定场景" label lives inside the view (the
    // placeholder), so the scene fills the whole widget and can grow larger.
    setupToolbar();

    // Debounced native-window resize: during an edge-drag the OSG child window
    // resize (a synchronous Vis command) is deferred until the resize settles,
    // so dragging the window edge stays smooth.
    m_resizeTimer = new QTimer(this);
    m_resizeTimer->setSingleShot(true);
    m_resizeTimer->setInterval(80);
    connect(m_resizeTimer, &QTimer::timeout, this, &VisSceneView::applyVisGeometry);

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

VisSceneView::~VisSceneView()
{
    shutdown();
}

// ═══════════════════════════════════════════════════════════════
// Toolbar (reset button only)
// ═══════════════════════════════════════════════════════════════

void VisSceneView::setupToolbar()
{
    // Floating overlays that must render ABOVE the native OSG child window.
    // Native widgets always stack above alien siblings, so the three toolbar
    // buttons are made native themselves; WA_DontCreateNativeAncestors mirrors
    // m_viewport so the alien m_containerWidget is not forced native (which the
    // Vis embedding relies on).  WA_TranslucentBackground lets the rounded pill
    // corners blend into the scene instead of showing an opaque rectangle.
    //
    // T-003：与 2D 视窗共用同一个浮层按钮组件（上方的 GlassButton）与同一套样式
    // （Theme::viewOverlayButtonStyle()）。原来这里在样式串后面追加的 3D 专属
    // 白色底（一段 QPushButton 的半透明背景覆盖）已经删掉——那正是「两个工具栏
    // 配色不一样」的根因。3D 侧没有模糊源（DWM blur-behind 在本机原生子窗口上不生效，
    // 见下方），所以共享组件的毛玻璃层什么都不画、保持透明，与 2D 的常态底色一致。
    const QString overlayBtnStyle = Theme::viewOverlayButtonStyle();

    m_resetButton = new GlassButton(m_containerWidget);
    m_resetButton->setText(QStringLiteral("复位"));
    m_resetButton->setCursor(Qt::PointingHandCursor);
    m_resetButton->setToolTip(QStringLiteral("复位到默认视角"));
    m_resetButton->setAttribute(Qt::WA_NativeWindow, true);
    m_resetButton->setAttribute(Qt::WA_DontCreateNativeAncestors, true);
    m_resetButton->setAttribute(Qt::WA_TranslucentBackground, true);
    m_resetButton->setStyleSheet(overlayBtnStyle);
    QObject::connect(m_resetButton, SIGNAL(clicked()), this, SLOT(resetViewNoAnim()));

    // "叠加历史" toggle: shows/hides the accumulated board-pose history frames.
    m_historyButton = new GlassButton(m_containerWidget);
    m_historyButton->setText(QStringLiteral("叠加历史"));
    m_historyButton->setCheckable(true);
    m_historyButton->setChecked(m_boardHistoryVisible);
    m_historyButton->setCursor(Qt::PointingHandCursor);
    m_historyButton->setToolTip(QStringLiteral("叠加显示历史帧的标定板姿态"));
    m_historyButton->setAttribute(Qt::WA_NativeWindow, true);
    m_historyButton->setAttribute(Qt::WA_DontCreateNativeAncestors, true);
    m_historyButton->setAttribute(Qt::WA_TranslucentBackground, true);
    m_historyButton->setStyleSheet(overlayBtnStyle);
    QObject::connect(m_historyButton, SIGNAL(toggled(bool)), this, SLOT(onHistoryToggled(bool)));

    // "偏差着色" toggle: the 3D half of the measurement colouring.  It lives in
    // the 3D toolbar because it changes what *this* view renders; the actual
    // colouring is computed by the tools panel, so the button only reports the
    // user's wish (deviationColoringToggled) and is answered by a re-published
    // snapshot — this view never reaches into the measurement code itself.
    m_deviationButton = new GlassButton(m_containerWidget);
    m_deviationButton->setText(QStringLiteral("偏差着色"));
    m_deviationButton->setObjectName(QStringLiteral("vis_deviation_toggle"));
    m_deviationButton->setCheckable(true);
    m_deviationButton->setCursor(Qt::PointingHandCursor);
    m_deviationButton->setToolTip(
        QStringLiteral("按测量结果给 3D 点云着色（与 2D 偏差图同一稳健色标）"));
    m_deviationButton->setAttribute(Qt::WA_NativeWindow, true);
    m_deviationButton->setAttribute(Qt::WA_DontCreateNativeAncestors, true);
    m_deviationButton->setAttribute(Qt::WA_TranslucentBackground, true);
    m_deviationButton->setStyleSheet(overlayBtnStyle);
    QObject::connect(m_deviationButton, &QPushButton::toggled, this,
                     &VisSceneView::deviationColoringToggled);

    // T-002 判据 1：原来那条「识别后可点击场景中的点选择填充」的视窗内提示
    // （m_pickHint）已删除——它改由 logRequested 进操作日志，见
    // maybeAnnouncePickHint()。

    // 3D 侧的真模糊：这三个浮层都挂上 DWM 的 blur-behind（见文件上方的说明）。
    applyBlurBehind(m_resetButton);
    applyBlurBehind(m_historyButton);
    applyBlurBehind(m_deviationButton);
}

// ═══════════════════════════════════════════════════════════════
// Core scene methods
// ═══════════════════════════════════════════════════════════════

void VisSceneView::updatePointCloud(const FrameBuffer::FloatBuf& xyz,
                                    const FrameBuffer::FloatBuf& rgb)
{
#ifdef HAS_RVBUST_VIS
    if (!d) return;
    if (!d->initialized) initVisEmbedding(d, m_viewport, this);
    if (!d->initialized) return;

    if (d->pointCloudHandle.type != 0 || d->pointCloudHandle.uid != 0) {
        d->view->Delete(d->pointCloudHandle);
        d->pointCloudHandle.Reset();
    }

    static const std::vector<float> kNoPoints;
    const std::vector<float>& pts = xyz ? *xyz : kNoPoints;
    const size_t numPts = pts.size() / 3;

    // Colour preparation, on the UI thread but without rebuilding a fresh
    // 8 MB array every time: when the producer's colour buffer already matches
    // the point count it is handed to Vis as-is, and the gray fallback reuses
    // one scratch buffer instead of allocating and filling a new one per call.
    const std::vector<float>* colorVec = nullptr;
    if (rgb && rgb->size() == numPts * 3) {
        colorVec = rgb.get();
    } else {
        const bool grayOnly = (!rgb || rgb->empty());
        if (d->scratchColors.size() != numPts * 3 || !grayOnly) {
            d->scratchColors.assign(numPts * 3, 0.8f);
            if (!grayOnly) {
                // qMin (not std::min): this file pulls in windows.h, whose
                // min/max macros break the std:: form without NOMINMAX.
                const size_t n = qMin(rgb->size(), numPts * 3);
                std::copy(rgb->begin(), rgb->begin() + n, d->scratchColors.begin());
            }
        }
        colorVec = &d->scratchColors;
    }

    const bool firstCloud = (d->pointCloudHandle.type == 0 && d->pointCloudHandle.uid == 0);
    d->pointCloudHandle = d->view->Point(pts, 2.0f, *colorVec);
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
    // T-002 判据 1：原本在这里显示视窗内提示；改成进操作日志。
    maybeAnnouncePickHint();
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
    // T-002 判据 1：原本在这里显示视窗内提示；改成进操作日志。
    maybeAnnouncePickHint();
#ifdef HAS_RVBUST_VIS
    if (d)
        d->wndProcCtx.hoverFeedArmed = enabled && !m_pickMarkers.empty();
#endif
}

// T-002 判据 1：进入「可点选」状态（识别出标记 + 已开点选）时，把原来那条
// 视窗内提示写进操作日志，一次识别只写一行（m_pickHintAnnounced 去重）。
void VisSceneView::maybeAnnouncePickHint()
{
    const bool pickable = m_pickEnabled && !m_pickMarkers.empty();
    if (!pickable) {
        m_pickHintAnnounced = false;   // 下次再识别时允许重新提示
        return;
    }
    if (m_pickHintAnnounced)
        return;
    m_pickHintAnnounced = true;
    emit logRequested(QStringLiteral("识别后可点击场景中的点选择填充"));
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
    m_pickHintAnnounced = false;
    ++m_pickQueryId;
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

    // Board-pose overlay handles are gone with the scene.
    m_boardFrameHandles.clear();
    m_boardHistoryHandles.clear();

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
// Board-pose overlay (stage 8, advisory)
// ═══════════════════════════════════════════════════════════════

void VisSceneView::setBoardFrame(const BoardFrame& frame)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;
    clearBoardFrame();

    // Rotate the board's local axes into the camera frame via its quaternion.
    const TransformTools::Rot3 r = TransformTools::quatToRot(
        frame.quat[0], frame.quat[1], frame.quat[2], frame.quat[3]);
    const std::array<float, 3> xAxis = { static_cast<float>(r[0]), static_cast<float>(r[3]), static_cast<float>(r[6]) };
    const std::array<float, 3> yAxis = { static_cast<float>(r[1]), static_cast<float>(r[4]), static_cast<float>(r[7]) };
    const std::array<float, 3> zAxis = { static_cast<float>(r[2]), static_cast<float>(r[5]), static_cast<float>(r[8]) };

    // Semi-transparent board plane, sized to the detected board.
    int h = addPlane(frame.extentXMM * MM_TO_M, frame.extentYMM * MM_TO_M,
                     1, 1, &frame.centerMM, &frame.quat, {0.25f, 0.65f, 1.0f});
    if (h >= 0) {
        m_boardFrameHandles.push_back(h);
        setObjectTransparency(h, 0.35f);
    }

    // RGB coordinate axes at the board center (x=red, y=green, z=blue).
    const float axisLen = (std::max)(1.0f, (std::max)(frame.extentXMM, frame.extentYMM) * 0.6f);
    auto arrowEnd = [&](const std::array<float, 3>& dir) -> std::array<float, 3> {
        return { frame.centerMM[0] + dir[0] * axisLen,
                 frame.centerMM[1] + dir[1] * axisLen,
                 frame.centerMM[2] + dir[2] * axisLen };
    };
    h = addArrow(frame.centerMM, arrowEnd(xAxis), 1.0f, {1.0f, 0.2f, 0.2f});
    if (h >= 0) m_boardFrameHandles.push_back(h);
    h = addArrow(frame.centerMM, arrowEnd(yAxis), 1.0f, {0.2f, 1.0f, 0.2f});
    if (h >= 0) m_boardFrameHandles.push_back(h);
    h = addArrow(frame.centerMM, arrowEnd(zAxis), 1.0f, {0.2f, 0.4f, 1.0f});
    if (h >= 0) m_boardFrameHandles.push_back(h);
#else
    (void)frame;
#endif
}

void VisSceneView::clearBoardFrame()
{
    for (int h : m_boardFrameHandles)
        removeObject(h);
    m_boardFrameHandles.clear();
}

void VisSceneView::setBoardHistory(const std::vector<BoardFrame>& frames)
{
#ifdef HAS_RVBUST_VIS
    if (!d || !d->initialized) return;
    clearBoardHistory();

    // Distinct palette cycles so consecutive frames stay distinguishable.
    static const std::array<std::array<float, 3>, 6> palette = {{
        {0.90f, 0.55f, 0.10f},  // orange
        {0.10f, 0.70f, 0.90f},  // cyan
        {0.55f, 0.90f, 0.10f},  // lime
        {0.90f, 0.10f, 0.55f},  // magenta
        {0.75f, 0.75f, 0.10f},  // yellow
        {0.45f, 0.55f, 0.95f},  // periwinkle
    }};

    for (const auto& f : frames) {
        const auto& col = palette[static_cast<std::size_t>(f.frameNo % 6)];
        int h = addPlane(f.extentXMM * MM_TO_M, f.extentYMM * MM_TO_M,
                         1, 1, &f.centerMM, &f.quat, col);
        if (h >= 0) {
            m_boardHistoryHandles.push_back(h);
            setObjectTransparency(h, 0.40f);
            setVisible(h, m_boardHistoryVisible);
        }
        // Frame-number label, offset slightly along the board normal.
        const TransformTools::Rot3 r = TransformTools::quatToRot(
            f.quat[0], f.quat[1], f.quat[2], f.quat[3]);
        const std::array<float, 3> n = { static_cast<float>(r[2]), static_cast<float>(r[5]), static_cast<float>(r[8]) };
        const std::array<float, 3> labelPos = {
            f.centerMM[0] + n[0] * 3.0f,
            f.centerMM[1] + n[1] * 3.0f,
            f.centerMM[2] + n[2] * 3.0f,
        };
        int t = addText(QString::number(f.frameNo), labelPos, 0.015f, {1.0f, 1.0f, 1.0f});
        if (t >= 0) {
            m_boardHistoryHandles.push_back(t);
            setVisible(t, m_boardHistoryVisible);
        }
    }
#else
    (void)frames;
#endif
}

void VisSceneView::clearBoardHistory()
{
    for (int h : m_boardHistoryHandles)
        removeObject(h);
    m_boardHistoryHandles.clear();
}

void VisSceneView::setBoardHistoryVisible(bool visible)
{
    m_boardHistoryVisible = visible;
    for (int h : m_boardHistoryHandles)
        setVisible(h, visible);
    if (m_historyButton)
        m_historyButton->setChecked(visible);
}

void VisSceneView::onHistoryToggled(bool visible)
{
    setBoardHistoryVisible(visible);
}

void VisSceneView::setDeviationColoringChecked(bool on)
{
    if (!m_deviationButton || m_deviationButton->isChecked() == on)
        return;
    // Reflect the panel-side state without echoing it back as a user toggle.
    const QSignalBlocker block(m_deviationButton);
    m_deviationButton->setChecked(on);
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

    // 1. Set shutdown flag FIRST — prevents showEvent/resizeEvent re-entry.
    //    Clearing `initializing` also cancels any pending embed retry, so no
    //    one-shot timer can embed a window into a torn-down viewport.
    m_shuttingDown = true;
    d->initialized = false;
    d->initializing = false;
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
        bool closed = false;
        {
            // Wait for any worker-thread pick query to finish before resetting
            // the view pointer.
            std::lock_guard<std::mutex> lg(d->viewMtx);
            if (d->visHwnd && IsWindow(d->visHwnd))
                ShowWindow(d->visHwnd, SW_HIDE);

            // Close() is a synchronous Vis command, so per PROJECT §3 it must
            // not run on the UI thread: it is issued on a worker here and this
            // thread only waits for it.
            //
            // The wait is bounded because the call can fail to return at all.
            // Measured with a freshly connected camera (round 6): issued from
            // ~VisSceneView() the call never came back — Vis::View::Close() →
            // Vis3d_Command_Execute ended up in MSVCP140!_Cnd_wait and stayed
            // there, so the process outlived the window (the round-6 blocker).
            // The identical call issued while the application is still alive
            // (MainWindow::closeEvent / aboutToQuit) returns in ~0.3 s; whether
            // the UI thread pumps messages meanwhile makes no difference.  The
            // close therefore happens there, and this bound is what keeps the
            // destructor path from re-introducing the hang if it ever runs
            // first (crash path, quit without closeEvent).
            const auto impl = d;   // keeps the impl (and its view) alive
            const auto done = std::make_shared<std::atomic<bool>>(false);
            std::thread worker([impl, done]() {
                if (impl->view)
                    impl->view->Close();
                done->store(true, std::memory_order_release);
            });
            for (int waited = 0;
                 waited < kViewCloseWaitMs && !done->load(std::memory_order_acquire);
                 waited += 10)
                QThread::msleep(10);
            if (done->load(std::memory_order_acquire)) {
                worker.join();
                d->view.reset();
                closed = true;
            } else {
                // Still inside Close(): the worker's own reference to the impl
                // keeps the view alive, so nothing is destroyed underneath it
                // and the process can exit without waiting any longer.
                worker.detach();
                RuntimeLog::log("3D: Vis close did not return within %d ms — "
                                "exiting without it", kViewCloseWaitMs);
            }
        }
        if (closed)
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

void VisSceneView::applyVisGeometry()
{
#ifdef HAS_RVBUST_VIS
    if (m_shuttingDown || !d || !m_containerWidget)
        return;

    const int cw = m_containerWidget->width();
    const int ch = m_containerWidget->height();
    if (cw <= 0 || ch <= 0)
        return;

    // Viewport fills the whole container (no title bar; the toolbar floats).
    if (d->initialized && d->visHwnd) {
        d->view->WindowSetRectangle(0, 0, cw, ch);
        positionVisWindow(*d, m_viewport);
    } else if (!d->initialized) {
        initVisEmbedding(d, m_viewport, this);
        positionVisWindow(*d, m_viewport);
    }
#else
    (void)0;
#endif
}

void VisSceneView::resizeEvent(QResizeEvent* event)
{
    QWidget::resizeEvent(event);
    if (!m_containerWidget) return;

    int cw = m_containerWidget->width();
    int ch = m_containerWidget->height();

    // Qt overlays reposition immediately (cheap).  The native Vis window
    // resize is deferred to applyVisGeometry() via m_resizeTimer so edge-drag
    // never blocks on a synchronous Vis command.
    if (m_placeholder)
        m_placeholder->setGeometry(0, 0, cw, ch);
    if (m_imageOverlay)
        m_imageOverlay->setGeometry(0, 0, cw, ch);
    if (m_viewport)
        m_viewport->setGeometry(0, 0, cw, ch);

    // Floating "复位" button (bottom-left) + "叠加历史" toggle.
    if (m_resetButton) {
        m_resetButton->adjustSize();
        m_resetButton->move(8, ch - m_resetButton->height() - 8);
        m_resetButton->raise();
    }
    if (m_historyButton) {
        m_historyButton->adjustSize();
        m_historyButton->move(8 + (m_resetButton ? m_resetButton->width() + 8 : 0),
                              ch - m_historyButton->height() - 8);
        m_historyButton->raise();
    }
    if (m_deviationButton) {
        m_deviationButton->adjustSize();
        m_deviationButton->move(8 + (m_resetButton ? m_resetButton->width() + 8 : 0)
                                    + (m_historyButton ? m_historyButton->width() + 8 : 0),
                                ch - m_deviationButton->height() - 8);
        m_deviationButton->raise();
    }
    if (m_resizeTimer)
        m_resizeTimer->start();
}

void VisSceneView::showEvent(QShowEvent* event)
{
    QWidget::showEvent(event);
    // Qt 在隐藏/显示之间可能重建原生窗口，accent 策略会跟着掉；露出来时补挂一次。
    applyBlurBehind(m_resetButton);
    applyBlurBehind(m_historyButton);
    applyBlurBehind(m_deviationButton);
#ifdef HAS_RVBUST_VIS
    if (m_shuttingDown) return;
    if (d && !d->initialized)
        applyVisGeometry();   // first show: embed the Vis window immediately
#endif
}
