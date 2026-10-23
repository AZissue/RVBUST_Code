#pragma once

// ── 会话备份文档（纯逻辑）──
//
// 备份 calibration_data_*.json 存的是"记录 + 相对会话目录的图片路径"。恢复
// 之后，撤销/清空会按记录里的路径删文件——所以恢复时有两件事必须同时成立，
// 否则一份改过的备份就能让一次撤销删掉会话目录外的文件：
//
//   1. 文档结构合法：版本、必需字段、每条记录的关键字段；
//   2. 解析出的每个路径都**落在该会话目录内**（绝对/相对、反斜杠、`..` 都
//      规范到同一套比较里）。
//
// 这里只做解析与路径判断，不写任何状态：调用方先拿完整结果，全部通过后再
// 一次性提交，校验失败时当前会话原封不动。
//
// 不做的事：不检查图片文件是否存在（备份可能只带了 JSON，图片稍后补），
// 也不检查路径指向的是不是图片——删除前 DataManager 还会用 isWithinDir()
// 再查一次，不依赖导入时的校验。

#include <QByteArray>
#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QString>
#include <vector>

namespace BackupDocument {

// 1 = 2.0/3.0 现行格式（模式 + records）。将来往文档里加字段（例如机器人
// 程序）时升到 2，并保留读 1 的能力。
constexpr int kVersion = 1;

struct Record {
    int index = 0;
    QString pngPath;          // 绝对路径，已确认在会话目录内
    QString plyPath;
    QString cameraTargetXyz;
    QString robotCapturePose;
    QString robotTargetXyz;
    float cameraErrorPct = -1.0f;
    int markerCount = 0;
};

struct ParseResult {
    bool ok = false;
    QString error;            // 一句可读中文，直接给现场
    int version = 0;
    bool eyeInHand = false;
    bool markerType = false;
    std::vector<Record> records;
};

// 盘符/反斜杠/`./` 统一后再比较，`a/../b` 这种也折叠掉。
inline QString cleanStoredPath(const QString& stored)
{
    QString p = stored.trimmed();
    p.replace(QLatin1Char('\\'), QLatin1Char('/'));
    return QDir::cleanPath(p);
}

// 存在的路径用规范路径（会解析符号链接/短文件名），不存在的退回清理后的
// 绝对路径——删除动作只会发生在存在的文件上，所以规范路径是首选。
inline QString canonicalOrClean(const QString& path)
{
    const QString c = QFileInfo(path).canonicalFilePath();
    QString p = c.isEmpty() ? QDir::cleanPath(QFileInfo(path).absoluteFilePath()) : c;
    p.replace(QLatin1Char('\\'), QLatin1Char('/'));
    while (p.size() > 1 && p.endsWith(QLatin1Char('/')))
        p.chop(1);
    return p;
}

// path 是否就是 dir 本身或 dir 的后代（不允许 dir/../x 这类"看名字像后代"
// 的路径：两者都先规范化）。
inline bool isWithinDir(const QString& dir, const QString& path)
{
    if (dir.trimmed().isEmpty() || path.trimmed().isEmpty())
        return false;

    const QString d = canonicalOrClean(dir);
    const QString f = canonicalOrClean(path);
    if (f.size() <= d.size())
        return false;
#ifdef Q_OS_WIN
    const Qt::CaseSensitivity cs = Qt::CaseInsensitive;
#else
    const Qt::CaseSensitivity cs = Qt::CaseSensitive;
#endif
    if (!f.startsWith(d, cs))
        return false;
    return f.at(d.size()) == QLatin1Char('/');
}

// 把备份里存的路径解析成会话目录内的绝对路径。绝对路径也接受（旧备份/手工
// 编辑过的备份），但同样必须落在会话目录内。
inline bool resolveStoredPath(const QString& sessionDir, const QString& stored,
                              QString* out, QString* error)
{
    const QString cleaned = cleanStoredPath(stored);
    if (cleaned.isEmpty()) {
        if (error) *error = QStringLiteral("路径为空");
        return false;
    }

    const QString full = QDir::isAbsolutePath(cleaned)
        ? cleaned
        : QDir::cleanPath(sessionDir + QLatin1Char('/') + cleaned);

    if (!isWithinDir(sessionDir, full)) {
        if (error)
            *error = QStringLiteral("%1 不在会话目录 %2 内")
                         .arg(cleaned, QDir::toNativeSeparators(sessionDir));
        return false;
    }
    if (out) *out = QDir::cleanPath(full);
    return true;
}

inline ParseResult parseForSession(const QByteArray& json, const QString& sessionDir)
{
    ParseResult r;

    if (sessionDir.trimmed().isEmpty()) {
        r.error = QStringLiteral("会话目录为空，无法判断路径归属");
        return r;
    }

    const QJsonDocument doc = QJsonDocument::fromJson(json);
    if (!doc.isObject()) {
        r.error = QStringLiteral("不是有效的备份文件（JSON 解析失败或根节点不是对象）");
        return r;
    }
    const QJsonObject root = doc.object();

    if (!root.value(QStringLiteral("version")).isDouble()) {
        r.error = QStringLiteral("备份缺少 version 字段");
        return r;
    }
    r.version = root.value(QStringLiteral("version")).toInt();
    if (r.version != kVersion) {
        r.error = QStringLiteral("备份版本 %1 不受支持（本程序可读版本 %2）")
                      .arg(r.version).arg(kVersion);
        return r;
    }

    const auto eye = root.value(QStringLiteral("eye_in_hand"));
    const auto marker = root.value(QStringLiteral("marker_type"));
    if (!eye.isBool() || !marker.isBool()) {
        r.error = QStringLiteral("备份缺少 eye_in_hand / marker_type 字段");
        return r;
    }
    r.eyeInHand = eye.toBool();
    r.markerType = marker.toBool();

    const auto recordsVal = root.value(QStringLiteral("records"));
    if (!recordsVal.isArray()) {
        r.error = QStringLiteral("备份缺少 records 数组");
        return r;
    }

    const QJsonArray arr = recordsVal.toArray();
    r.records.reserve(static_cast<size_t>(arr.size()));

    for (int i = 0; i < arr.size(); ++i) {
        if (!arr.at(i).isObject()) {
            r.error = QStringLiteral("第 %1 条记录不是对象").arg(i + 1);
            r.records.clear();
            return r;
        }
        const QJsonObject obj = arr.at(i).toObject();

        Record rec;
        const auto idx = obj.value(QStringLiteral("index"));
        if (!idx.isDouble() || idx.toInt() < 1) {
            r.error = QStringLiteral("第 %1 条记录的 index 缺失或非法").arg(i + 1);
            r.records.clear();
            return r;
        }
        rec.index = idx.toInt();

        const auto png = obj.value(QStringLiteral("png_path"));
        const auto ply = obj.value(QStringLiteral("ply_path"));
        if (!png.isString() || png.toString().trimmed().isEmpty()) {
            r.error = QStringLiteral("第 %1 条记录缺少 png_path").arg(i + 1);
            r.records.clear();
            return r;
        }
        if (!ply.isString() || ply.toString().trimmed().isEmpty()) {
            r.error = QStringLiteral("第 %1 条记录缺少 ply_path").arg(i + 1);
            r.records.clear();
            return r;
        }

        QString pathError;
        if (!resolveStoredPath(sessionDir, png.toString(), &rec.pngPath, &pathError)) {
            r.error = QStringLiteral("第 %1 条记录的 png_path %2").arg(i + 1).arg(pathError);
            r.records.clear();
            return r;
        }
        if (!resolveStoredPath(sessionDir, ply.toString(), &rec.plyPath, &pathError)) {
            r.error = QStringLiteral("第 %1 条记录的 ply_path %2").arg(i + 1).arg(pathError);
            r.records.clear();
            return r;
        }

        rec.cameraTargetXyz = obj.value(QStringLiteral("camera_target_xyz")).toString();
        rec.robotCapturePose = obj.value(QStringLiteral("robot_capture_pose")).toString();
        rec.robotTargetXyz = obj.value(QStringLiteral("robot_target_xyz")).toString();
        rec.cameraErrorPct =
            static_cast<float>(obj.value(QStringLiteral("camera_error_pct")).toDouble(-1.0));
        rec.markerCount = obj.value(QStringLiteral("marker_count")).toInt(0);

        r.records.push_back(rec);
    }

    r.ok = true;
    return r;
}

} // namespace BackupDocument
