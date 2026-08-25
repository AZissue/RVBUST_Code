#include "logic/LogManager.h"
#include <QDir>
#include <QFile>
#include <QTextStream>
#include <QDateTime>
#include <QCoreApplication>

static QMap<QString, QString> LEVEL_LABELS = {
    {"info",    "INFO"},
    {"success", " OK "},
    {"warning", "WARN"},
    {"error",   "ERR "},
};

LogManager::LogManager(QObject* parent)
    : QObject(parent)
{
}

void LogManager::info(const QString& message)    { addEntry(message, QStringLiteral("info")); }
void LogManager::success(const QString& message) { addEntry(message, QStringLiteral("success")); }
void LogManager::warning(const QString& message) { addEntry(message, QStringLiteral("warning")); }
void LogManager::error(const QString& message)   { addEntry(message, QStringLiteral("error")); }

void LogManager::addEntry(const QString& message, const QString& level)
{
    auto ts = QDateTime::currentDateTime().toString(QStringLiteral("HH:mm:ss"));
    m_entries.emplace_back(ts, message, level);
    // Bound memory usage: keep only the most recent entries in RAM.  The file
    // is unaffected (appends everything).
    while (m_entries.size() > MAX_IN_MEMORY_ENTRIES)
        m_entries.erase(m_entries.begin());
    emit logAdded(ts, message, level);
    writeToFile(ts, message, level);
}

void LogManager::writeToFile(const QString& ts, const QString& message, const QString& level)
{
    try {
        ensureLogFile();
        QFile file(m_logFilePath);
        if (file.open(QIODevice::Append | QIODevice::Text)) {
            QTextStream stream(&file);
            stream.setCodec("UTF-8");
            stream << "[" << ts << "] [" << LEVEL_LABELS.value(level, "----") << "] " << message << "\n";
        }
    } catch (...) {
        // File write failure should not affect UI log display
    }
}

void LogManager::ensureLogFile()
{
    auto dateStr = QDateTime::currentDateTime().toString("yyyyMMdd");
    auto logsDir = QCoreApplication::applicationDirPath() + QStringLiteral("/logs");
    auto expected = logsDir + QStringLiteral("/app_%1.log").arg(dateStr);

    if (m_logFilePath != expected) {
        QDir().mkpath(logsDir);
        m_logFilePath = expected;
    }
}

std::vector<std::tuple<QString, QString, QString>> LogManager::allEntries() const
{
    return m_entries;
}

void LogManager::clear()
{
    m_entries.clear();
}
