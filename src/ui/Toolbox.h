#pragma once

// 工具箱：分类树展示 ModuleRegistry 内容，支持折叠/展开、搜索过滤、拖拽/双击实例化模块。

#include <QLineEdit>
#include <QTreeWidget>
#include <QWidget>

namespace rvc {

// 拖拽使用的 MIME 类型，负载为模块类型 ID
inline constexpr const char* kModuleMimeType = "application/x-rvc-module";

class Toolbox : public QWidget {
    Q_OBJECT
public:
    explicit Toolbox(QWidget* parent = nullptr);

    // 从注册表重建分类树
    void reload();

    // 聚焦到搜索框（可绑定全局快捷键）
    void focusSearch();

Q_SIGNALS:
    // 双击叶子模块（或回车）触发：在画布中心实例化
    void moduleActivated(const QString& typeId);

private:
    class ModuleTree : public QTreeWidget {
    public:
        explicit ModuleTree(QWidget* parent = nullptr);
    protected:
        void startDrag(Qt::DropActions supportedActions) override;
        QMimeData* mimeData(const QList<QTreeWidgetItem*>& items) const override;
    };

    void buildTree();
    void applyFilter(const QString& text);
    void onItemDoubleClicked(QTreeWidgetItem* item, int column);

    ModuleTree* tree_ = nullptr;
    QLineEdit* search_ = nullptr;
};

} // namespace rvc
