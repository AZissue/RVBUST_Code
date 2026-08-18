#include "Toolbox.h"

#include <QDrag>
#include <QMimeData>
#include <QTreeWidgetItem>
#include <QVBoxLayout>

#include "core/ModuleRegistry.h"

namespace rvc {

Toolbox::ModuleTree::ModuleTree(QWidget* parent) : QTreeWidget(parent)
{
    setHeaderHidden(true);
    setRootIsDecorated(true);
    setIndentation(12);
    setDragEnabled(true);
    setDragDropMode(QAbstractItemView::DragOnly);
    setSelectionMode(QAbstractItemView::SingleSelection);
    setExpandsOnDoubleClick(false); // 双击用于实例化模块，不折叠
}

void Toolbox::ModuleTree::startDrag(Qt::DropActions supportedActions)
{
    auto* item = currentItem();
    if (!item || item->childCount() > 0 || item->data(0, Qt::UserRole).toString().isEmpty())
        return; // 只有叶子模块项可拖拽
    QTreeWidget::startDrag(supportedActions);
}

QMimeData* Toolbox::ModuleTree::mimeData(const QList<QTreeWidgetItem*>& items) const
{
    auto* mime = new QMimeData;
    if (!items.isEmpty()) {
        const QString typeId = items.first()->data(0, Qt::UserRole).toString();
        if (!typeId.isEmpty() && typeId != QStringLiteral("__category__")) {
            mime->setData(QLatin1String(kModuleMimeType), typeId.toUtf8());
            mime->setText(items.first()->text(0));
        }
    }
    return mime;
}

Toolbox::Toolbox(QWidget* parent) : QWidget(parent)
{
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(8, 8, 8, 8);
    layout->setSpacing(8);

    search_ = new QLineEdit(this);
    search_->setPlaceholderText(QStringLiteral("搜索模块…"));
    search_->setClearButtonEnabled(true);
    layout->addWidget(search_);

    tree_ = new ModuleTree(this);
    layout->addWidget(tree_, 1);

    connect(search_, &QLineEdit::textChanged, this, &Toolbox::applyFilter);
    connect(tree_, &QTreeWidget::itemDoubleClicked,
            this, &Toolbox::onItemDoubleClicked);

    reload();
}

void Toolbox::reload()
{
    buildTree();
    applyFilter(search_->text());
}

void Toolbox::focusSearch()
{
    if (search_)
        search_->setFocus();
}

void Toolbox::buildTree()
{
    tree_->clear();
    const auto grouped = ModuleRegistry::instance().byCategory();
    for (const auto& [category, infos] : grouped) {
        auto* catItem = new QTreeWidgetItem(tree_, {QString::fromStdString(category)});
        catItem->setData(0, Qt::UserRole, QStringLiteral("__category__"));
        QFont catFont = catItem->font(0);
        catFont.setBold(true);
        catItem->setFont(0, catFont);
        catItem->setForeground(0, QColor(QStringLiteral("#8B8D98"))); // ink-secondary
        catItem->setFlags(Qt::ItemIsEnabled); // 不可选、不可拖

        for (const auto& info : infos) {
            auto* modItem = new QTreeWidgetItem(catItem,
                                                {QString::fromStdString(info.displayName)});
            modItem->setData(0, Qt::UserRole, QString::fromStdString(info.typeId));
            modItem->setToolTip(0, QString::fromStdString(info.typeId));
            modItem->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable | Qt::ItemIsDragEnabled);
        }
    }
    tree_->expandAll();
}

void Toolbox::applyFilter(const QString& text)
{
    const QString key = text.trimmed().toLower();
    for (int i = 0; i < tree_->topLevelItemCount(); ++i) {
        auto* catItem = tree_->topLevelItem(i);
        bool anyVisible = false;
        for (int j = 0; j < catItem->childCount(); ++j) {
            auto* modItem = catItem->child(j);
            const bool match = key.isEmpty() ||
                               modItem->text(0).toLower().contains(key);
            modItem->setHidden(!match);
            if (match)
                anyVisible = true;
        }
        catItem->setHidden(!anyVisible);
        if (anyVisible && !key.isEmpty())
            catItem->setExpanded(true);
    }
}

void Toolbox::onItemDoubleClicked(QTreeWidgetItem* item, int /*column*/)
{
    if (!item || item->childCount() > 0)
        return;
    const QString typeId = item->data(0, Qt::UserRole).toString();
    if (!typeId.isEmpty() && typeId != QStringLiteral("__category__"))
        Q_EMIT moduleActivated(typeId);
}

} // namespace rvc
