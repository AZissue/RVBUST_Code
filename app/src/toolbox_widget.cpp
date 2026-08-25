#include "toolbox_widget.h"

#include "node_titles.h"

#include <QLineEdit>
#include <QMimeData>
#include <QTreeWidget>
#include <QVBoxLayout>

#include <map>

namespace app {

namespace {

class ToolboxTree : public QTreeWidget {
public:
    using QTreeWidget::QTreeWidget;

protected:
    QMimeData* mimeData(const QList<QTreeWidgetItem*>& items) const override {
        auto* m = new QMimeData;
        if (!items.isEmpty()) {
            const QString type = items.first()->data(0, Qt::UserRole).toString();
            if (!type.isEmpty()) {
                m->setData("application/x-pcsearch-node", type.toUtf8());
            }
        }
        return m;
    }
};

}  // namespace

ToolboxWidget::ToolboxWidget(QWidget* parent) : QWidget(parent) {
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(6);

    search_ = new QLineEdit(this);
    search_->setClearButtonEnabled(true);
    layout->addWidget(search_);

    tree_ = new ToolboxTree(this);
    tree_->setHeaderHidden(true);
    tree_->setDragEnabled(true);
    tree_->setDragDropMode(QAbstractItemView::DragOnly);
    tree_->setIndentation(14);
    layout->addWidget(tree_, 1);

    connect(search_, &QLineEdit::textChanged, this, &ToolboxWidget::applyFilter);
    connect(tree_, &QTreeWidget::itemDoubleClicked, this,
            [this](QTreeWidgetItem* item, int) {
                const QString type = item->data(0, Qt::UserRole).toString();
                if (!type.isEmpty()) emit nodeActivated(type);
            });
}

void ToolboxWidget::populate(const std::vector<pcsearch::pipeline::NodeInfo>& infos,
                             bool zh) {
    tree_->clear();
    std::map<QString, QTreeWidgetItem*> categories;
    for (const auto& info : infos) {
        const QString category =
            categoryTitle(info.category, zh);
        auto it = categories.find(category);
        if (it == categories.end()) {
            auto* category_item = new QTreeWidgetItem(tree_);
            category_item->setText(0, category);
            category_item->setFlags(Qt::ItemIsEnabled);
            it = categories.emplace(category, category_item).first;
        }
        auto* node_item = new QTreeWidgetItem(it->second);
        node_item->setText(0, nodeTitle(info.type, zh));
        node_item->setData(0, Qt::UserRole, QString::fromStdString(info.type));
        node_item->setToolTip(0, QString::fromStdString(info.type));
        node_item->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable |
                            Qt::ItemIsDragEnabled);
    }
    tree_->expandAll();
    applyFilter(search_->text());
}

void ToolboxWidget::setSearchPlaceholder(const QString& text) {
    search_->setPlaceholderText(text);
}

void ToolboxWidget::focusSearch() {
    search_->setFocus();
    search_->selectAll();
}

void ToolboxWidget::applyFilter(const QString& text) {
    const QString needle = text.trimmed();
    for (int c = 0; c < tree_->topLevelItemCount(); ++c) {
        QTreeWidgetItem* category = tree_->topLevelItem(c);
        bool category_visible = needle.isEmpty();
        for (int r = 0; r < category->childCount(); ++r) {
            QTreeWidgetItem* node_item = category->child(r);
            const bool match =
                needle.isEmpty() ||
                node_item->text(0).contains(needle, Qt::CaseInsensitive) ||
                node_item->toolTip(0).contains(needle, Qt::CaseInsensitive) ||
                category->text(0).contains(needle, Qt::CaseInsensitive);
            node_item->setHidden(!match);
            category_visible = category_visible || match;
        }
        category->setHidden(!category_visible);
    }
}

}  // namespace app
