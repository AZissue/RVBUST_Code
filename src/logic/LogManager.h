#pragma once
#include <QObject>
#include <QString>
#include <vector>
#include <tuple>

class LogManager : public QObject {
    Q_OBJECT
public:
    // Upper bound on in-memory log entries (the file keeps everything for the
    // day; memory only keeps the latest entries for the future UI display).
    static constexpr size_t MAX_IN_MEMORY_ENTRIES = 1000;

    explicit LogManager(QObject* parent = nullptr);

    void info(const QString& message);
    void success(const QString& message);
    void warning(const QString& message);
    void error(const QString& message);

    std::vector<std::tuple<QString, QString, QString>> allEntries() const;
    void clear();

signals:
    void logAdded(const QString& timestamp, const QString& message, const QString& level);

private:
    void addEntry(const QString& message, const QString& level);
    void writeToFile(const QString& ts, const QString& message, const QString& level);
    void ensureLogFile();

    std::vector<std::tuple<QString, QString, QString>> m_entries;
    QString m_logFilePath;
};
