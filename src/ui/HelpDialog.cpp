#include "ui/HelpDialog.h"

#include "AppInfo.h"
#include "logic/HelpContent.h"
#include "ui/Theme.h"

#include <QDesktopServices>
#include <QHBoxLayout>
#include <QLabel>
#include <QListWidget>
#include <QPushButton>
#include <QScrollBar>
#include <QTextBrowser>
#include <QUrl>
#include <QVBoxLayout>

HelpDialog::HelpDialog(QWidget* parent)
    : QDialog(parent)
{
    setWindowTitle(QStringLiteral("使用说明 — ") + AppInfo::title());
    // 同 ToolsPanel：非模态、可自由缩放/最大化。说明文字很多，窗口不能被内容
    // 尺寸锁死；右栏自己会滚动。
    setMinimumSize(760, 480);
    resize(1000, 700);
    setWindowFlags(windowFlags() | Qt::WindowMinMaxButtonsHint);
    setAttribute(Qt::WA_DeleteOnClose, false);
    buildUi();
}

void HelpDialog::buildUi()
{
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(16, 16, 16, 16);
    layout->setSpacing(12);

    auto* header = new QLabel(AppInfo::summary(), this);
    header->setWordWrap(true);
    header->setStyleSheet(QStringLiteral("font-size: %1px; font-weight: 600; color: %2;")
                          .arg(Theme::FONT_H2).arg(Theme::TEXT_TITLE));
    layout->addWidget(header);

    auto* row = new QHBoxLayout();
    row->setSpacing(16);

    m_chapterList = new QListWidget(this);
    // 与 ToolsPanel 一样给稳定 objectName：UI 自动化按名字找控件。
    m_chapterList->setObjectName(QStringLiteral("help_chapter_list"));
    m_chapterList->setFixedWidth(168);
    m_chapterList->setStyleSheet(QStringLiteral(
        "QListWidget { background: %1; border: 1px solid %2; border-radius: %3px;"
        " font-size: %4px; }"
        "QListWidget::item { padding: 8px 10px; }"
        "QListWidget::item:selected { background: %6; color: %5; }")
        .arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS)
        .arg(Theme::FONT_BODY).arg(Theme::PRIMARY)
        .arg(Theme::withAlpha(Theme::PRIMARY, 0.12)));
    row->addWidget(m_chapterList);

    m_browser = new QTextBrowser(this);
    m_browser->setObjectName(QStringLiteral("help_browser"));
    m_browser->setOpenLinks(false);          // 章节间跳转由我们自己处理
    m_browser->setOpenExternalLinks(false);
    m_browser->setFrameShape(QFrame::NoFrame);
    m_browser->setStyleSheet(QStringLiteral(
        "QTextBrowser { background: %1; border: 1px solid %2; border-radius: %3px;"
        " padding: 12px 16px; font-size: %4px; color: %5; }")
        .arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS)
        .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY));
    row->addWidget(m_browser, 1);

    layout->addLayout(row, 1);

    // 目录选中 → 换正文；正文里的 [某章](#id) 链接 → 反向选中目录。
    connect(m_chapterList, &QListWidget::currentRowChanged,
            this, &HelpDialog::selectRow);
    connect(m_browser, &QTextBrowser::anchorClicked, this, [this](const QUrl& url) {
        if (url.scheme().isEmpty() && !url.fragment().isEmpty()) {
            showChapter(url.fragment());
            return;
        }
        QDesktopServices::openUrl(url);
    });

    auto* btnRow = new QHBoxLayout();
    auto* hint = new QLabel(QStringLiteral("按 F1 可随时打开本说明"), this);
    hint->setStyleSheet(QStringLiteral("color: %1; font-size: %2px;")
                        .arg(Theme::TEXT_HINT).arg(Theme::FONT_HINT));
    btnRow->addWidget(hint);
    btnRow->addStretch();

    auto* btnClose = new QPushButton(QStringLiteral("关闭"), this);
    btnClose->setFixedSize(80, 32);
    btnClose->setStyleSheet(QStringLiteral(R"(
        QPushButton { color: %1; background: transparent; border: 1px solid %2;
                      border-radius: 4px; font-size: %3px; }
        QPushButton:hover { border-color: %1; }
    )").arg(Theme::TEXT_BODY).arg(Theme::BORDER_DEFAULT).arg(Theme::FONT_BODY));
    connect(btnClose, &QPushButton::clicked, this, &QDialog::accept);
    btnRow->addWidget(btnClose);

    layout->addLayout(btnRow);

    loadChapters();
}

void HelpDialog::loadChapters()
{
    int count = 0;
    const auto* table = HelpContent::chapters(count);

    for (int i = 0; i < count; ++i) {
        m_chapterList->addItem(QString::fromUtf8(table[i].title));
    }
    if (m_chapterList->count() > 0)
        m_chapterList->setCurrentRow(0);
}

void HelpDialog::selectRow(int row)
{
    int count = 0;
    const auto* table = HelpContent::chapters(count);
    if (row < 0 || row >= count)
        return;

    // 正文里的版本占位符在这里换成 AppInfo 的真实版本号：帮助文本自己绝不写死
    // 版本（2026-10-08 界面还显示 V1.0，就是因为版本号被写死在三处）。
    const std::string body = HelpContent::renderBody(table[row].body,
                                                    AppInfo::version().toStdString());
    m_browser->setMarkdown(QString::fromUtf8(body.c_str()));
    m_browser->verticalScrollBar()->setValue(0);   // 换章回到开头
}

void HelpDialog::showChapter(const QString& id)
{
    const int index = HelpContent::chapterIndexOf(id.toUtf8().constData());
    if (index < 0)
        return;
    m_chapterList->setCurrentRow(index);   // 触发 selectRow()
}
