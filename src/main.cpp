#include <windows.h>
#include <cstdio>

// windows.h pollutes the global namespace with macro names like ERROR
#ifdef ERROR
#undef ERROR
#endif

#include "app/MainWindow.h"
#include "logic/CameraManager.h"
#include "ui/Theme.h"

#include <QApplication>
#include <QFont>
#include <QDir>
#include <QFile>
#include <QSettings>
#include <QTextStream>
#include <QDateTime>
#include <QtGlobal>

#include <atomic>
#include <memory>
#include <thread>

// ── Early-boot file logger (before LogManager is available) ──

static FILE* g_earlyLog = nullptr;

static void earlyLog(const char* fmt, ...)
{
    if (!g_earlyLog) return;
    va_list args;
    va_start(args, fmt);
    vfprintf(g_earlyLog, fmt, args);
    va_end(args);
    fflush(g_earlyLog);
}

// ── Qt message handler → file ──

static void qtMsgHandler(QtMsgType type, const QMessageLogContext& ctx, const QString& msg)
{
    if (!g_earlyLog) return;
    const char* level = "DEBUG";
    switch (type) {
    case QtDebugMsg:    level = "DEBUG"; break;
    case QtInfoMsg:     level = "INFO "; break;
    case QtWarningMsg:  level = "WARN "; break;
    case QtCriticalMsg: level = "CRIT "; break;
    case QtFatalMsg:    level = "FATAL"; break;
    }
    QByteArray local = msg.toLocal8Bit();
    earlyLog("[Qt-%s] %s (%s:%d)\n", level, local.constData(),
             ctx.file ? ctx.file : "", ctx.line);
    if (type == QtFatalMsg) {
        if (g_earlyLog) { fclose(g_earlyLog); g_earlyLog = nullptr; }
        abort();
    }
}

// ── SEH exception filter (任务 3.3) ──
//
// The camera is the expensive asset here, so a crash must not leave a process
// sitting on it.  The old handler showed a *modal* message box and then kept
// going (EXCEPTION_CONTINUE_SEARCH): the box waits for a click that may never
// come, so an unattended machine held the 3D camera open indefinitely — which
// is exactly the "被占用" the operator then sees on the next start.
//
// New sequence, in this order and unconditionally:
//   1. write the crash record (code, module, address, time) to the runtime log;
//   2. try one bounded (<= 2 s) release on a *separate* thread, so a hung SDK
//      call cannot block the exit;
//   3. TerminateProcess — the OS then reclaims every handle, which is what
//      actually frees the device.
//
// Trade-off (calling into the SDK from a crash handler): the SDK release is
// skipped when the faulting module *is* the SDK/driver, because an access
// violation there means its own state is untrustworthy and a further call can
// only make things worse (or fault again inside the filter).  In that case the
// log says so explicitly and we go straight to termination — process exit is
// sufficient to release the device.  When the fault is elsewhere (our code, Qt,
// OSG) a SystemShutdown is attempted, but it is only best-effort: `done` is
// ignored after the bound expires.
static LONG WINAPI sehExceptionFilter(EXCEPTION_POINTERS* exInfo)
{
    const DWORD code = exInfo->ExceptionRecord->ExceptionCode;
    void* addr = exInfo->ExceptionRecord->ExceptionAddress;

    // Re-entry guard: if the release thread itself faults, this filter runs a
    // second time (on that thread).  Terminate immediately then — no retry, no
    // recursion, no chance of a loop that never exits.
    static std::atomic<int> busy{0};
    if (busy.fetch_add(1) != 0)
        TerminateProcess(GetCurrentProcess(), code);

    // path[] must outlive the `if`: moduleName points into it.
    char path[MAX_PATH] = {};
    const char* moduleName = "未知模块";
    MEMORY_BASIC_INFORMATION mbi = {};
    if (VirtualQuery(addr, &mbi, sizeof(mbi)) && mbi.AllocationBase) {
        if (GetModuleFileNameA((HMODULE)mbi.AllocationBase, path, sizeof(path))) {
            const char* basename = strrchr(path, '\\');
            moduleName = basename ? basename + 1 : path;
        }
    }

    // 1. Crash record → runtime log (same file the normal log lines go to).
    earlyLog("[CRASH] SEH 0x%08X at 0x%p module=%s\n", code, addr, moduleName);
    earlyLog("[CRASH] time=%s\n",
             QDateTime::currentDateTime().toString("yyyy-MM-dd HH:mm:ss.zzz")
                 .toLocal8Bit().constData());
    earlyLog("[CRASH] ThreadId=%lu — 进程将立即退出以释放相机；无模态框、无等待。\n",
             GetCurrentThreadId());
    earlyLog("[CRASH] 详细异常记录见 Windows 事件查看器 (来源: Application Error, "
             "异常码 0x%08X)。\n", code);

    // 2. Bounded release attempt on an independent thread.
    const bool sdkFault = strstr(moduleName, "RVC") || strstr(moduleName, "rvc")
                       || strstr(moduleName, "HandEye") || strstr(moduleName, "handeye");
    if (sdkFault) {
        earlyLog("[CRASH] 故障模块为 %s —— SDK 状态不可信，跳过 SDK 释放调用，直接退出。\n",
                 moduleName);
    } else {
        // shared_ptr, not a stack flag: the thread is detached and must not read
        // a local of a frame that is about to end.
        auto done = std::make_shared<std::atomic<bool>>(false);
        std::thread([done]() {
            CameraManager::emergencyRelease();
            done->store(true);
        }).detach();
        const int budgetMs = 2000;   // ≤ 2 s, never longer
        for (int waited = 0; waited < budgetMs && !done->load(); waited += 50)
            Sleep(50);
        earlyLog("[CRASH] 相机释放尝试结束 finished=%d (<= %d ms)\n",
                 done->load() ? 1 : 0, budgetMs);
    }

    if (g_earlyLog) { fclose(g_earlyLog); g_earlyLog = nullptr; }

    // 3. Exit now.  TerminateProcess (not exit()) so no atexit/destructor can
    //    hang on the still-broken SDK, and the handles are reclaimed at once.
    TerminateProcess(GetCurrentProcess(), code);
    return EXCEPTION_EXECUTE_HANDLER;   // not reached
}

// Separate function to allow SEH __try/__except (no C++ locals requiring unwinding)
static int runEventLoop(QApplication& app)
{
    int ret = 0;
    __try {
        ret = app.exec();
    } __except (sehExceptionFilter(GetExceptionInformation())) {
        ret = -1;
    }
    return ret;
}

// ── Open early-boot log file ──

static void openEarlyLog()
{
    QString logDir = QDir::cleanPath(
        QCoreApplication::applicationDirPath() + QStringLiteral("/logs"));
    QDir().mkpath(logDir);
    QString dateStr = QDateTime::currentDateTime().toString("yyyyMMdd");
    // Runtime/technical log (startup, SDK calls, timings, exceptions, crashes).
    // User-facing operations go to app_<date>.log via LogManager.
    QString path = logDir + QStringLiteral("/runtime_%1.log").arg(dateStr);
    g_earlyLog = fopen(path.toLocal8Bit().constData(), "a");
    // Redirect stderr to the runtime log (GUI apps have no console) and make
    // it unbuffered so a crash never loses the tail of the diagnostics.
    if (g_earlyLog) {
        freopen(path.toLocal8Bit().constData(), "a", stderr);
        setvbuf(stderr, nullptr, _IONBF, 0);
    }
}

// ── Entry point ──

int main(int argc, char* argv[])
{
    // High-priority: create QApplication first so we can use QDir etc.
    QApplication app(argc, argv);

    openEarlyLog();
    earlyLog("=== HandEyeCalibrationTool v1.0.0 runtime start ===\n");
    earlyLog("exe: %s\n",
             QDir::toNativeSeparators(QCoreApplication::applicationDirPath())
                 .toLocal8Bit().constData());
    earlyLog("qt: %s (build %s)\n", qVersion(), QT_VERSION_STR);
    earlyLog("cwd: %s\n",
             QDir::toNativeSeparators(QDir::currentPath()).toLocal8Bit().constData());
    earlyLog("config: %s\n",
             QDir::toNativeSeparators(
                 QSettings(QSettings::IniFormat, QSettings::UserScope,
                           QStringLiteral("RVBUST"), QStringLiteral("HandEyeTool"))
                     .fileName()).toLocal8Bit().constData());

    qInstallMessageHandler(qtMsgHandler);

    // Set default font (instead of * { font-family: ... } in stylesheet
    // which crashes Qt on internal native widgets)
    QFont defaultFont(QStringLiteral("Microsoft YaHei"), Theme::FONT_BODY);
    app.setFont(defaultFont);

    app.setStyleSheet(Theme::globalStylesheet());
    app.setApplicationName(QStringLiteral("HandEyeCalibrationTool"));
    app.setApplicationVersion(QStringLiteral("1.0.0"));
    app.setOrganizationName(QStringLiteral("RVBUST"));

    SetUnhandledExceptionFilter(sehExceptionFilter);

    MainWindow window;
    window.show();

    // Force initial paint/layout before entering event loop
    app.processEvents();

    int ret = runEventLoop(app);

    if (g_earlyLog) { fclose(g_earlyLog); g_earlyLog = nullptr; }
    return ret;
}
