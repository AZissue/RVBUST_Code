#include <windows.h>
#include <cstdio>

// windows.h pollutes the global namespace with macro names like ERROR
#ifdef ERROR
#undef ERROR
#endif

#include "app/MainWindow.h"
#include "ui/Theme.h"

#include <QApplication>
#include <QFont>
#include <QMessageBox>
#include <QDir>
#include <QFile>
#include <QSettings>
#include <QTextStream>
#include <QDateTime>
#include <QtGlobal>

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

// ── SEH exception filter ──

static LONG WINAPI sehExceptionFilter(EXCEPTION_POINTERS* exInfo)
{
    DWORD code = exInfo->ExceptionRecord->ExceptionCode;
    void* addr = exInfo->ExceptionRecord->ExceptionAddress;
    earlyLog("[CRASH] SEH exception 0x%08X at address 0x%p\n", code, addr);

    // Try to identify which module caused the crash
    MEMORY_BASIC_INFORMATION mbi = {};
    const char* moduleName = "未知模块";
    if (VirtualQuery(addr, &mbi, sizeof(mbi)) && mbi.AllocationBase) {
        char path[MAX_PATH] = {};
        if (GetModuleFileNameA((HMODULE)mbi.AllocationBase, path, sizeof(path))) {
            const char* basename = strrchr(path, '\\');
            moduleName = basename ? basename + 1 : path;
            earlyLog("[CRASH] Module: %s\n", moduleName);
        }
    }

    if (g_earlyLog) { fclose(g_earlyLog); g_earlyLog = nullptr; }

    // Build a specific error message based on the crashing module
    QString detail;
    if (strstr(moduleName, "RVC") || strstr(moduleName, "rvc")) {
        detail = QStringLiteral("RVC 相机 SDK (RVC.dll) 内部发生访问违规。\n"
                                "请检查相机驱动是否正确安装，相机是否已连接。");
    } else if (strstr(moduleName, "HandEye") || strstr(moduleName, "handeye")) {
        detail = QStringLiteral("HandEye 手眼标定 SDK 内部发生访问违规。");
    } else if (strstr(moduleName, "osg") || strstr(moduleName, "OpenThreads")) {
        detail = QStringLiteral("OSG 3D 可视化引擎 (%1) 内部发生访问违规。").arg(moduleName);
    } else if (strstr(moduleName, "Qt5") || strstr(moduleName, "Qt6")) {
        detail = QStringLiteral("Qt 框架 (%1) 内部发生访问违规。").arg(moduleName);
    } else {
        detail = QStringLiteral("底层 DLL (%1) 内部发生访问违规 (0x%2)。")
                     .arg(moduleName).arg(code, 8, 16, QLatin1Char('0'));
    }

    QMessageBox::critical(nullptr, QStringLiteral("底层 SDK 崩溃"),
        QStringLiteral("%1\n\n应用将退出，请重启后重试。").arg(detail));
    return EXCEPTION_CONTINUE_SEARCH;
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
