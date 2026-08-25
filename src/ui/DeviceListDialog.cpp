#include "ui/DeviceListDialog.h"
#include "ui/Theme.h"
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QtConcurrent/QtConcurrentRun>

DeviceListDialog::DeviceListDialog(QWidget* parent,
                                   const std::vector<DeviceEntry>& devices,
                                   std::function<std::vector<DeviceEntry>()> refreshFn)
    : QDialog(parent)
    , m_refreshFn(std::move(refreshFn))
{
    setWindowTitle(QStringLiteral("选择相机设备"));
    setMinimumSize(480, 280);
    resize(520, 340);
    m_refreshWatcher = new QFutureWatcher<std::vector<DeviceEntry>>(this);
    connect(m_refreshWatcher, &QFutureWatcher<std::vector<DeviceEntry>>::finished,
            this, &DeviceListDialog::onRefreshFinished);
    buildUi(devices);
}

void DeviceListDialog::buildUi(const std::vector<DeviceEntry>& devices)
{
    auto* mainLayout = new QVBoxLayout(this);
    mainLayout->setContentsMargins(20, 16, 20, 16);
    mainLayout->setSpacing(12);

    // Header row: title + refresh button
    auto* headerRow = new QHBoxLayout();
    auto* title = new QLabel(QStringLiteral("选择相机设备"), this);
    title->setStyleSheet(QStringLiteral("font-size: %1px; font-weight: 600; color: %2;")
                         .arg(Theme::FONT_H2).arg(Theme::TEXT_TITLE));
    headerRow->addWidget(title);
    headerRow->addStretch();

    m_btnRefresh = new QPushButton(QStringLiteral("刷新"), this);
    m_btnRefresh->setFixedSize(64, 28);
    m_btnRefresh->setStyleSheet(QStringLiteral(R"(
        QPushButton { color: %1; background: transparent; border: 1px solid %1;
                      border-radius: 4px; font-size: %2px; }
        QPushButton:hover { background-color: %3; }
    )").arg(Theme::PRIMARY).arg(Theme::FONT_HINT).arg(Theme::PRIMARY_LIGHT));
    connect(m_btnRefresh, &QPushButton::clicked, this, &DeviceListDialog::onRefresh);
    headerRow->addWidget(m_btnRefresh);
    mainLayout->addLayout(headerRow);

    // Table
    m_table = new QTableWidget(this);
    m_table->setColumnCount(3);
    m_table->setHorizontalHeaderLabels({
        QStringLiteral("名称"),
        QStringLiteral("序列号"),
        QStringLiteral("状态")
    });
    m_table->horizontalHeader()->setStretchLastSection(true);
    m_table->horizontalHeader()->setSectionResizeMode(0, QHeaderView::Stretch);
    m_table->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
    m_table->verticalHeader()->setVisible(false);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setSelectionMode(QAbstractItemView::SingleSelection);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setAlternatingRowColors(true);
    m_table->setShowGrid(false);
    m_table->setStyleSheet(QStringLiteral(R"(
        QTableWidget { background-color: %1; border: 1px solid %2; border-radius: %3px;
                       font-size: %4px; color: %5; }
        QTableWidget::item { padding: 6px 10px; }
        QTableWidget::item:selected { background-color: rgba(22,119,255,0.12); color: %5; }
        QHeaderView::section { background-color: %1; color: %6; font-size: %4px;
                               border: none; padding: 6px 10px; font-weight: 600; }
    )").arg(Theme::BG_MAIN).arg(Theme::BORDER_DEFAULT).arg(Theme::BORDER_RADIUS)
       .arg(Theme::FONT_BODY).arg(Theme::TEXT_BODY).arg(Theme::TEXT_HINT));

    connect(m_table, &QTableWidget::itemSelectionChanged, this, &DeviceListDialog::onSelectionChanged);
    connect(m_table, &QTableWidget::cellDoubleClicked, this, &DeviceListDialog::onDoubleClicked);
    mainLayout->addWidget(m_table);

    populateTable(devices);

    // Bottom buttons
    auto* btnRow = new QHBoxLayout();
    btnRow->addStretch();

    m_btnOk = new QPushButton(QStringLiteral("确定"), this);
    m_btnOk->setFixedSize(80, 32);
    m_btnOk->setEnabled(false);
    m_btnOk->setStyleSheet(QStringLiteral(R"(
        QPushButton { color: #FFF; background-color: %1; border: none;
                      border-radius: 4px; font-size: %2px; font-weight: 600; }
        QPushButton:hover { background-color: %3; }
        QPushButton:disabled { background-color: #D9D9D9; color: #999; }
    )").arg(Theme::PRIMARY).arg(Theme::FONT_BODY).arg(Theme::PRIMARY_LIGHT));
    connect(m_btnOk, &QPushButton::clicked, this, &QDialog::accept);
    btnRow->addWidget(m_btnOk);

    auto* btnCancel = new QPushButton(QStringLiteral("取消"), this);
    btnCancel->setFixedSize(80, 32);
    btnCancel->setStyleSheet(QStringLiteral(R"(
        QPushButton { color: %1; background: transparent; border: 1px solid %2;
                      border-radius: 4px; font-size: %3px; }
        QPushButton:hover { border-color: %1; }
    )").arg(Theme::TEXT_BODY).arg(Theme::BORDER_DEFAULT).arg(Theme::FONT_BODY));
    connect(btnCancel, &QPushButton::clicked, this, &QDialog::reject);
    btnRow->addWidget(btnCancel);

    mainLayout->addLayout(btnRow);
}

void DeviceListDialog::populateTable(const std::vector<DeviceEntry>& devices)
{
    m_table->setRowCount(static_cast<int>(devices.size()));
    m_selectedSerial.clear();
    if (m_btnOk)  // populateTable() is also called from buildUi() before m_btnOk exists
        m_btnOk->setEnabled(false);

    for (int row = 0; row < static_cast<int>(devices.size()); ++row) {
        const auto& dev = devices[row];

        // Name
        auto* nameItem = new QTableWidgetItem(dev.name.isEmpty()
            ? QStringLiteral("未知设备") : dev.name);

        // Serial
        auto* snItem = new QTableWidgetItem(dev.serial);

        // Status
        QString statusText;
        QColor  statusColor;
        if (dev.occupied) {
            statusText  = QStringLiteral("占用");
            statusColor = QColor(Theme::ERROR);
        } else {
            statusText  = QStringLiteral("可用");
            statusColor = QColor(Theme::SUCCESS);
        }
        auto* statusItem = new QTableWidgetItem(statusText);
        statusItem->setForeground(statusColor);
        statusItem->setData(Qt::UserRole, dev.occupied);

        m_table->setItem(row, 0, nameItem);
        m_table->setItem(row, 1, snItem);
        m_table->setItem(row, 2, statusItem);

        // Occupied rows cannot be selected
        if (dev.occupied) {
            for (int col = 0; col < 3; ++col) {
                auto* item = m_table->item(row, col);
                if (item) {
                    item->setFlags(item->flags() & ~Qt::ItemIsSelectable);
                    item->setForeground(QColor(Theme::TEXT_HINT));
                }
            }
        }
    }
}

QString DeviceListDialog::selectedSerial() const
{
    return m_selectedSerial;
}

void DeviceListDialog::onSelectionChanged()
{
    auto selected = m_table->selectedItems();
    if (selected.isEmpty()) {
        m_btnOk->setEnabled(false);
        m_selectedSerial.clear();
        return;
    }

    int row = selected.first()->row();
    auto* snItem = m_table->item(row, 1);
    m_selectedSerial = snItem ? snItem->text() : QString();
    m_btnOk->setEnabled(!m_selectedSerial.isEmpty());
}

void DeviceListDialog::onRefresh()
{
    if (!m_refreshFn || m_refreshing)
        return;

    // Give immediate feedback: the scan can take a few seconds (GigE bus
    // enumeration) and must not block the dialog's event loop.
    m_refreshing = true;
    m_btnRefresh->setEnabled(false);
    m_btnRefresh->setText(QStringLiteral("搜索中..."));
    m_btnRefresh->setStyleSheet(QStringLiteral(R"(
        QPushButton, QPushButton:disabled {
            color: #FFFFFF;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 rgba(22,119,255,0.55),
                                        stop:1 rgba(22,119,255,0.12));
            border: 1px solid %1;
            border-radius: 4px;
            font-size: %2px;
        }
    )").arg(Theme::PRIMARY).arg(Theme::FONT_HINT));

    m_refreshWatcher->setFuture(QtConcurrent::run(m_refreshFn));
}

void DeviceListDialog::onRefreshFinished()
{
    m_refreshing = false;
    m_btnRefresh->setEnabled(true);
    m_btnRefresh->setText(QStringLiteral("刷新"));
    m_btnRefresh->setStyleSheet(QStringLiteral(R"(
        QPushButton { color: %1; background: transparent; border: 1px solid %1;
                      border-radius: 4px; font-size: %2px; }
        QPushButton:hover { background-color: %3; }
    )").arg(Theme::PRIMARY).arg(Theme::FONT_HINT).arg(Theme::PRIMARY_LIGHT));

    const auto devices = m_refreshWatcher->result();
    populateTable(devices);
    if (devices.empty()) {
        // Keep the user informed when nothing was found.
        m_btnRefresh->setText(QStringLiteral("未找到设备，重试"));
    }
}

void DeviceListDialog::onDoubleClicked(int row, int /*col*/)
{
    // Occupied devices are blocked from single-click selection via item flags,
    // but double-click bypasses selection — guard it explicitly.
    auto* statusItem = m_table->item(row, 2);
    if (statusItem && statusItem->data(Qt::UserRole).toBool())
        return;

    auto* snItem = m_table->item(row, 1);
    if (!snItem) return;
    m_selectedSerial = snItem->text();
    if (!m_selectedSerial.isEmpty())
        accept();
}
