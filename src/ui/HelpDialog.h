#pragma once

#include <QDialog>

class QListWidget;
class QTextBrowser;

// 使用说明窗口：左侧章节、右侧正文。
//
// 内容不是写在这里的，而是 src/logic/HelpContent.h 的一张纯数据表 —— 与
// MeasureMethods.h 同一套路数（UTF-8 的 const char*，界面侧只负责转换与渲染）。
// 这样"每个测量方法都有说明""目录与正文一一对应""帮助里不写死版本号"这几条
// 都能被单测盯住，而不是靠人记得同步。
//
// 非模态、常驻一份（同 ToolsPanel）：用户一边看说明一边操作主窗口是常态，
// 模态窗口会把主界面锁住。窗口只在首次点「帮助」时创建。
class HelpDialog : public QDialog {
    Q_OBJECT
public:
    explicit HelpDialog(QWidget* parent = nullptr);

    // 打开到某一章（默认第一章）。已打开时只切章、不再重建。
    void showChapter(const QString& id);

private:
    void buildUi();
    // 把 HelpContent 的章节填进左列表 + 右正文。
    void loadChapters();
    void selectRow(int row);

    QListWidget*  m_chapterList = nullptr;
    QTextBrowser* m_browser     = nullptr;
};
