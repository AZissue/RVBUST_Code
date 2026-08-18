#include "Solution.h"

#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>

namespace rvc {

bool Solution::save(const QString& filePath, QString* err) const
{
    QJsonArray modulesArr;
    for (const auto& [id, node] : process_->nodes()) {
        QJsonObject m;
        m["id"] = id;
        m["type"] = QString::fromStdString(node.typeId);
        m["name"] = QString::fromStdString(node.module->name());
        m["x"] = node.x;
        m["y"] = node.y;
        m["params"] = node.module->saveParams();
        modulesArr.append(m);
    }

    QJsonArray linksArr;
    for (const auto& l : process_->links()) {
        QJsonObject j;
        j["fromNode"] = l.fromNode;
        j["fromPort"] = QString::fromStdString(l.fromPort);
        j["toNode"] = l.toNode;
        j["toPort"] = QString::fromStdString(l.toPort);
        linksArr.append(j);
    }

    QJsonObject root;
    root["version"] = 1;
    root["modules"] = modulesArr;
    root["links"] = linksArr;

    QFile file(filePath);
    if (!file.open(QIODevice::WriteOnly)) {
        if (err) *err = QStringLiteral("cannot open file for writing: %1").arg(filePath);
        return false;
    }
    file.write(QJsonDocument(root).toJson(QJsonDocument::Indented));
    return true;
}

bool Solution::load(const QString& filePath, QString* err)
{
    auto fail = [err](const QString& msg) {
        if (err) *err = msg;
        return false;
    };

    QFile file(filePath);
    if (!file.open(QIODevice::ReadOnly))
        return fail(QStringLiteral("cannot open file: %1").arg(filePath));

    QJsonParseError parseErr{};
    const QJsonDocument doc = QJsonDocument::fromJson(file.readAll(), &parseErr);
    if (parseErr.error != QJsonParseError::NoError || !doc.isObject())
        return fail(QStringLiteral("invalid solution JSON: %1").arg(parseErr.errorString()));

    const QJsonObject root = doc.object();

    // 先清空再重建；任何一步失败都返回错误
    Process rebuilt;

    const QJsonArray modulesArr = root["modules"].toArray();
    for (const auto& v : modulesArr) {
        const QJsonObject m = v.toObject();
        const QString type = m["type"].toString();
        // 保持文件中的节点 ID，使连线表无需重映射
        const int newId = m.contains("id")
                              ? rebuilt.addNodeWithId(type.toStdString(), m["id"].toInt())
                              : rebuilt.addNode(type.toStdString());
        if (newId < 0)
            return fail(QStringLiteral("unknown module type or duplicated node id: %1").arg(type));

        ProcessNode* node = rebuilt.node(newId);
        node->x = m["x"].toDouble();
        node->y = m["y"].toDouble();
        if (m.contains("name"))
            node->module->setName(m["name"].toString().toStdString());
        node->module->loadParams(m["params"].toObject());
    }

    const QJsonArray linksArr = root["links"].toArray();
    for (const auto& v : linksArr) {
        const QJsonObject j = v.toObject();
        std::string linkErr;
        if (!rebuilt.addLink(j["fromNode"].toInt(), j["fromPort"].toString().toStdString(),
                             j["toNode"].toInt(), j["toPort"].toString().toStdString(), &linkErr)) {
            return fail(QStringLiteral("invalid link in solution file: %1")
                            .arg(QString::fromStdString(linkErr)));
        }
    }

    *process_ = std::move(rebuilt);
    return true;
}

} // namespace rvc
