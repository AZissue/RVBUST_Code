#include "logic/RuntimeLog.h"

#include <cstdio>
#include <cstdarg>

#include <QDateTime>

namespace RuntimeLog {

void log(const char* fmt, ...)
{
    char buf[1024];
    va_list args;
    va_start(args, fmt);
    vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);

    const auto ts = QDateTime::currentDateTime().toString(QStringLiteral("HH:mm:ss.zzz"));
    fprintf(stderr, "[%s] %s\n", qPrintable(ts), buf);
}

} // namespace RuntimeLog
