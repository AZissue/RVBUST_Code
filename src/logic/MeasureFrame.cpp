#include "logic/MeasureFrame.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSaveFile>

namespace MeasureFrame {

namespace {

bool fail(QString* error, const QString& message)
{
    if (error)
        *error = message;
    return false;
}

// A file named in the manifest must be a plain file name inside the frame
// directory: "../x.grid" would let a crafted frame read anything on disk.
bool isPlainFileName(const QString& name)
{
    return !name.isEmpty() && !name.contains(QLatin1Char('/'))
           && !name.contains(QLatin1Char('\\')) && name != QLatin1String("..")
           && name != QLatin1String(".");
}

bool gridSizeMatches(int w, int h, std::size_t points)
{
    if (w <= 0 || h <= 0)
        return false;
    const std::size_t cells = static_cast<std::size_t>(w) * static_cast<std::size_t>(h);
    // Guard against overflow on absurd headers.
    if (cells / static_cast<std::size_t>(w) != static_cast<std::size_t>(h))
        return false;
    if (cells > (std::size_t(1) << 32))
        return false;
    return points == cells * 3;
}

QJsonObject rectToJson(const RoiRect& r)
{
    QJsonObject o;
    // QJsonValue has no unambiguous constructor from int (bool/double both fit).
    o.insert(QStringLiteral("left"), static_cast<double>(r.left));
    o.insert(QStringLiteral("top"), static_cast<double>(r.top));
    o.insert(QStringLiteral("right"), static_cast<double>(r.right));
    o.insert(QStringLiteral("bottom"), static_cast<double>(r.bottom));
    return o;
}

RoiRect rectFromJson(const QJsonObject& o)
{
    RoiRect r;
    r.left = o.value(QStringLiteral("left")).toInt();
    r.top = o.value(QStringLiteral("top")).toInt();
    r.right = o.value(QStringLiteral("right")).toInt();
    r.bottom = o.value(QStringLiteral("bottom")).toInt();
    return r;
}

QJsonObject rowToJson(const ResultRow& r)
{
    QJsonObject o;
    o.insert(QStringLiteral("method"), r.method);
    o.insert(QStringLiteral("value"), r.value);
    o.insert(QStringLiteral("unit"), r.unit);
    o.insert(QStringLiteral("points"), static_cast<double>(r.points));
    o.insert(QStringLiteral("confidence"), r.confidence);
    return o;
}

ResultRow rowFromJson(const QJsonObject& o)
{
    ResultRow r;
    r.method = o.value(QStringLiteral("method")).toString();
    r.value = o.value(QStringLiteral("value")).toString();
    r.unit = o.value(QStringLiteral("unit")).toString();
    r.points = o.value(QStringLiteral("points")).toInt();
    r.confidence = o.value(QStringLiteral("confidence")).toString();
    return r;
}

} // namespace

bool writeGrid(const QString& path, const std::vector<double>& grid, int w, int h,
               QString* error)
{
    if (!gridSizeMatches(w, h, grid.size())) {
        return fail(error, QStringLiteral("网格尺寸与点数不一致：%1×%2 需要 %3 个数，实际 %4 个")
                               .arg(w).arg(h)
                               .arg(static_cast<qulonglong>(std::size_t(w) * std::size_t(h) * 3))
                               .arg(static_cast<qulonglong>(grid.size())));
    }
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly))
        return fail(error, QStringLiteral("无法写入网格文件：%1").arg(path));

    // Same header and payload as tests/measure_truth's *.grid writer, so a
    // frame captured here can be read by the truth harness unchanged.
    const QByteArray header = QStringLiteral("%1 %2\n").arg(w).arg(h).toLatin1();
    if (file.write(header) != header.size())
        return fail(error, QStringLiteral("写网格头失败：%1").arg(path));

    std::vector<float> payload(grid.size());
    for (std::size_t i = 0; i < grid.size(); ++i)
        payload[i] = static_cast<float>(grid[i]);
    const qint64 bytes = static_cast<qint64>(payload.size() * sizeof(float));
    if (file.write(reinterpret_cast<const char*>(payload.data()), bytes) != bytes)
        return fail(error, QStringLiteral("写网格数据失败：%1").arg(path));

    if (!file.commit())
        return fail(error, QStringLiteral("提交网格文件失败：%1").arg(path));
    return true;
}

bool readGrid(const QString& path, int* w, int* h, std::vector<double>* grid,
              QString* error)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return fail(error, QStringLiteral("打不开网格文件：%1").arg(path));

    QByteArray header;
    bool sawNewline = false;
    while (header.size() < 64) {
        char c = 0;
        if (file.read(&c, 1) != 1)
            break;
        if (c == '\n') {
            sawNewline = true;
            break;
        }
        header.append(c);
    }
    if (!sawNewline || header.isEmpty())
        return fail(error, QStringLiteral("网格头非法（应为 \"<宽> <高>\"）：%1").arg(path));

    const QList<QByteArray> parts = header.trimmed().split(' ');
    bool okW = false, okH = false;
    const int gw = parts.size() == 2 ? parts.at(0).toInt(&okW) : 0;
    const int gh = parts.size() == 2 ? parts.at(1).toInt(&okH) : 0;
    if (!okW || !okH || gw <= 0 || gh <= 0)
        return fail(error, QStringLiteral("网格头非法（应为 \"<宽> <高>\"）：%1").arg(path));

    const qint64 expected = static_cast<qint64>(gw) * gh * 3 * static_cast<qint64>(sizeof(float));
    const qint64 available = file.size() - file.pos();
    if (expected <= 0 || available != expected) {
        return fail(error, QStringLiteral("网格数据长度不符：头写 %1×%2，文件里 %3 字节，应为 %4 字节")
                               .arg(gw).arg(gh).arg(available).arg(expected));
    }

    std::vector<float> payload(static_cast<std::size_t>(gw) * gh * 3);
    const qint64 got = file.read(reinterpret_cast<char*>(payload.data()), expected);
    if (got != expected)
        return fail(error, QStringLiteral("读取网格数据失败：%1").arg(path));

    if (grid) {
        grid->resize(payload.size());
        for (std::size_t i = 0; i < payload.size(); ++i)
            (*grid)[i] = payload[i];
    }
    if (w)
        *w = gw;
    if (h)
        *h = gh;
    return true;
}

QString suggestDir(const QString& root, const QString& methodId, const QDateTime& when)
{
    QString safe;
    for (const QChar ch : methodId) {
        safe.append((ch.isLetterOrNumber() && ch.unicode() < 128) || ch == QLatin1Char('_')
                        ? ch
                        : QLatin1Char('_'));
    }
    if (safe.isEmpty())
        safe = QStringLiteral("measure");
    const QString leaf = QStringLiteral("%1_%2")
                             .arg(safe, when.toString(QStringLiteral("yyyyMMdd_HHmmss")));
    return QDir(root).filePath(QStringLiteral("measure_frames/%1").arg(leaf));
}

bool save(const QString& dir, const Manifest& manifest,
          const std::vector<double>& grid, const QImage& image, QString* error)
{
    if (dir.isEmpty())
        return fail(error, QStringLiteral("未指定测量帧目录"));
    if (!gridSizeMatches(manifest.gridW, manifest.gridH, grid.size())) {
        return fail(error, QStringLiteral("网格尺寸与点数不一致：%1×%2 需要 %3 个数，实际 %4 个")
                               .arg(manifest.gridW).arg(manifest.gridH)
                               .arg(static_cast<qulonglong>(std::size_t(manifest.gridW)
                                                            * std::size_t(manifest.gridH) * 3))
                               .arg(static_cast<qulonglong>(grid.size())));
    }
    if (manifest.methodId.isEmpty())
        return fail(error, QStringLiteral("缺少测量方法 id，无法保存测量帧"));

    QDir parent;
    if (!parent.mkpath(dir))
        return fail(error, QStringLiteral("无法创建测量帧目录：%1").arg(dir));

    if (!writeGrid(QDir(dir).filePath(QString::fromLatin1(kGridName)), grid,
                   manifest.gridW, manifest.gridH, error))
        return false;

    QJsonObject root;
    root.insert(QStringLiteral("schema"), manifest.schema);
    root.insert(QStringLiteral("method"), manifest.methodId);
    root.insert(QStringLiteral("captured_at"), manifest.capturedAt);
    root.insert(QStringLiteral("note"), manifest.note);
    {
        QJsonObject g;
        g.insert(QStringLiteral("file"), QString::fromLatin1(kGridName));
        g.insert(QStringLiteral("w"), static_cast<double>(manifest.gridW));
        g.insert(QStringLiteral("h"), static_cast<double>(manifest.gridH));
        root.insert(QStringLiteral("grid"), g);
    }
    if (!image.isNull()) {
        const QString imagePath = QDir(dir).filePath(QString::fromLatin1(kImageName));
        if (!image.save(imagePath, "PNG"))
            return fail(error, QStringLiteral("无法写入测量帧图像：%1").arg(imagePath));
        QJsonObject im;
        im.insert(QStringLiteral("file"), QString::fromLatin1(kImageName));
        im.insert(QStringLiteral("w"), static_cast<double>(image.width()));
        im.insert(QStringLiteral("h"), static_cast<double>(image.height()));
        root.insert(QStringLiteral("image"), im);
    }
    {
        QJsonArray rois;
        for (const RoiRect& r : manifest.rois)
            rois.append(rectToJson(r));
        root.insert(QStringLiteral("rois"), rois);
    }
    {
        QJsonArray rows;
        for (const ResultRow& r : manifest.rows)
            rows.append(rowToJson(r));
        root.insert(QStringLiteral("rows"), rows);
    }
    {
        QJsonObject primary;
        primary.insert(QStringLiteral("key"), manifest.primaryKey);
        primary.insert(QStringLiteral("value"), manifest.primaryValue);
        primary.insert(QStringLiteral("has"), manifest.hasPrimary);
        root.insert(QStringLiteral("primary"), primary);
    }
    root.insert(QStringLiteral("extra"), manifest.extra);

    // frame.json is written last on purpose: a directory without it is not a
    // frame, so a half-written capture can never be replayed as if it were one.
    QSaveFile jsonFile(QDir(dir).filePath(QString::fromLatin1(kManifestName)));
    if (!jsonFile.open(QIODevice::WriteOnly))
        return fail(error, QStringLiteral("无法写入测量帧清单：%1").arg(dir));
    const QByteArray bytes = QJsonDocument(root).toJson(QJsonDocument::Indented);
    if (jsonFile.write(bytes) != bytes.size())
        return fail(error, QStringLiteral("写测量帧清单失败：%1").arg(dir));
    if (!jsonFile.commit())
        return fail(error, QStringLiteral("提交测量帧清单失败：%1").arg(dir));
    return true;
}

bool load(const QString& dir, Manifest* manifest, std::vector<double>* grid,
          QImage* image, QString* error)
{
    if (dir.isEmpty())
        return fail(error, QStringLiteral("未指定测量帧目录"));

    QFile jsonFile(QDir(dir).filePath(QString::fromLatin1(kManifestName)));
    if (!jsonFile.open(QIODevice::ReadOnly))
        return fail(error, QStringLiteral("该目录不是测量帧（缺少 %1）：%2")
                               .arg(QString::fromLatin1(kManifestName), dir));
    const QJsonDocument doc = QJsonDocument::fromJson(jsonFile.readAll());
    if (!doc.isObject())
        return fail(error, QStringLiteral("测量帧清单不是有效的 JSON：%1").arg(dir));
    const QJsonObject root = doc.object();

    const QString schema = root.value(QStringLiteral("schema")).toString();
    if (schema != QLatin1String(kSchema)) {
        return fail(error, QStringLiteral("不支持的测量帧版本「%1」（本程序读 %2）")
                               .arg(schema.isEmpty() ? QStringLiteral("空") : schema,
                                    QString::fromLatin1(kSchema)));
    }

    Manifest m;
    m.schema = schema;
    m.methodId = root.value(QStringLiteral("method")).toString();
    m.capturedAt = root.value(QStringLiteral("captured_at")).toString();
    m.note = root.value(QStringLiteral("note")).toString();
    if (m.methodId.isEmpty())
        return fail(error, QStringLiteral("测量帧清单缺少方法 id：%1").arg(dir));

    const QJsonObject g = root.value(QStringLiteral("grid")).toObject();
    const QString gridName = g.value(QStringLiteral("file")).toString();
    if (!isPlainFileName(gridName))
        return fail(error, QStringLiteral("测量帧清单里的网格文件名非法：%1").arg(gridName));
    m.gridW = g.value(QStringLiteral("w")).toInt();
    m.gridH = g.value(QStringLiteral("h")).toInt();

    int fileW = 0, fileH = 0;
    std::vector<double> points;
    const QString gridPath = QDir(dir).filePath(gridName);
    if (!readGrid(gridPath, &fileW, &fileH, &points, error))
        return false;
    if (fileW != m.gridW || fileH != m.gridH) {
        return fail(error, QStringLiteral("测量帧清单与网格头不一致：清单 %1×%2，网格 %3×%4")
                               .arg(m.gridW).arg(m.gridH).arg(fileW).arg(fileH));
    }

    const QJsonObject im = root.value(QStringLiteral("image")).toObject();
    QImage loaded;
    if (!im.isEmpty()) {
        const QString imageName = im.value(QStringLiteral("file")).toString();
        if (!isPlainFileName(imageName))
            return fail(error, QStringLiteral("测量帧清单里的图像文件名非法：%1").arg(imageName));
        loaded.load(QDir(dir).filePath(imageName));
        if (loaded.isNull())
            return fail(error, QStringLiteral("测量帧图像读不出来：%1").arg(imageName));
        m.hasImage = true;
        m.imageW = loaded.width();
        m.imageH = loaded.height();
    }

    for (const QJsonValue& v : root.value(QStringLiteral("rois")).toArray()) {
        const RoiRect r = rectFromJson(v.toObject());
        if (!r.valid())
            return fail(error, QStringLiteral("测量帧里的 ROI 非法：(%1,%2)-(%3,%4)")
                                   .arg(r.left).arg(r.top).arg(r.right).arg(r.bottom));
        if (m.hasImage && (r.left < 0 || r.top < 0 || r.right >= m.imageW
                           || r.bottom >= m.imageH)) {
            return fail(error, QStringLiteral("测量帧里的 ROI 超出图像范围：(%1,%2)-(%3,%4)，图像 %5×%6")
                                   .arg(r.left).arg(r.top).arg(r.right).arg(r.bottom)
                                   .arg(m.imageW).arg(m.imageH));
        }
        m.rois.append(r);
    }

    for (const QJsonValue& v : root.value(QStringLiteral("rows")).toArray())
        m.rows.append(rowFromJson(v.toObject()));

    const QJsonObject primary = root.value(QStringLiteral("primary")).toObject();
    m.primaryKey = primary.value(QStringLiteral("key")).toString();
    m.primaryValue = primary.value(QStringLiteral("value")).toDouble();
    m.hasPrimary = primary.value(QStringLiteral("has")).toBool();

    m.extra = root.value(QStringLiteral("extra")).toObject();

    if (manifest)
        *manifest = m;
    if (grid)
        *grid = std::move(points);
    if (image)
        *image = loaded;
    return true;
}

} // namespace MeasureFrame
