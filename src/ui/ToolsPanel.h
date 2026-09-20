#pragma once

#include <QDialog>
#include <QListWidget>
#include <QStackedWidget>
#include <QCheckBox>
#include <QComboBox>
#include <QLabel>
#include <QLineEdit>
#include <QMap>
#include <QPushButton>
#include <QSpinBox>
#include <QTableWidget>
#include <QTextEdit>
#include <QVector>
#include <QString>
#include <QStringList>
#include <QWidget>
#include <QFutureWatcher>
#include <QDoubleSpinBox>
#include <array>
#include <memory>
#include <vector>
#include "logic/CalibrationService.h"
#include "logic/FrameBuffer.h"
#include "logic/MeasureTools.h"
#include "ui/MeasurementSnapshot.h"

class MeasurePage;

// Non-modal tools panel (v2.0).  Left: tool list.  Right: the selected tool.
// Tools: Euclidean distance, coordinate transform (walk-point validation), and
// one entry per measurement method (P3) sharing a single MeasurePage base.
class ToolsPanel : public QDialog {
    Q_OBJECT
public:
    explicit ToolsPanel(QWidget* parent = nullptr);

    void setRobotStatus(const QString& text, bool ok);
    void setRobotConnected(bool connected);
    // Mirror of AppConfig "auto_read_robot_pose".  Programmatic, so it does not
    // re-emit robotAutoReadToggled (MainWindow is the single writer of the key).
    void setRobotAutoRead(bool on);

    // ── Measurement tools (aligned with the Python 3D 测量一体化工具) ──
    // Each method is its own entry in the left list and its own MeasurePage in
    // the stack (P3); the panel only owns what the pages share: the captured
    // grid, the ROI rectangles and the repeatability series store.
    // The 3D grid of the last capture, handed over by refcount.  The image size
    // is needed because the dragged ROI is in image pixels while the grid is in
    // point-map cells — the two do not have to share a resolution.
    void setMeasurementCloud(const FrameBuffer::DoubleBuf& grid, int gridW, int gridH,
                             int imageW, int imageH);
    // A rectangle dragged on the 2D view (image pixels).  Landed per the active
    // method's declared ROI requirement (MeasureTools::planRoiDrag) — the user
    // is told what happened, never silently restarted.
    void onRoiSelected(const QRect& rect);
    void clearMeasurementRois();
    // Mirror of the 3D view's toolbar toggle.  Applying it re-runs the last
    // measurement so the colouring appears (or disappears) immediately.
    void setDeviationColoring(bool on);

    // 像素→3D 工具页的「在线/离线」开关状态（离线 = 用主 2D 视窗取点）。
    bool pixelTo3DOffline() const { return !m_p2dOnline; }
    // 在线模式且当前工具页就是「像素→3D」：主窗口据此把点击/查询结果推给本页。
    bool onlinePixelTo3DActive() const
    {
        return m_p2dOnline && m_stack != nullptr && m_p2dPage != nullptr
            && m_stack->currentWidget() == m_p2dPage;
    }

signals:
    // Emitted when the panel's own 3D-colouring checkbox is toggled, so the 3D
    // toolbar button can follow it.
    void deviationColoringChanged(bool on);
    // Everything the 2D/3D views need to paint the measurement pages.
    void measurementUpdated(const Measurement::Snapshot& snapshot);
    // ROI rectangles to draw on the 2D image (image pixels).
    void roisChanged(const QVector<QRect>& rois, const QStringList& labels);
    void robotConnectRequested(const QString& host, quint16 port,
                               int protocol, int format, double scale,
                               quint8 unitId, quint16 startAddress);
    void robotDisconnectRequested();
    void robotSimulateConnectRequested();
    void robotAutoReadToggled(bool on);
    // Measurement explanation / result lines (P4).  MainWindow writes them into
    // the operation log; the panel itself never touches the logger.
    void logMessage(const QString& line);

    // 离线模式：请主窗口把主 2D 视窗冻结成这张图
    void pixelTo3DOfflineImageRequested(const QString& imagePath);
    // 离开离线模式 / 关掉工具页 / 清空目录：请主窗口解冻
    void pixelTo3DOfflineImageEnded();
    // 在线模式：请主窗口用当前采集帧执行一次像素→3D 查询
    void pixelTo3DOnlineQueryRequested(int pixelX, int pixelY);

    // 用户点了「用当前会话」：请主窗口把当前会话目录与每组位姿给回来
    void calibrationSessionRequested();

public slots:
    // 主窗口回答：folder = 当前会话目录；poseLines = 每组数据的机器人位姿（顺序即采集顺序）；
    // eyeInHand / concentric 与主窗口当前选择一致，两个下拉框要对齐过去。
    void useCurrentSession(const QString& folder, const QStringList& poseLines,
                           bool eyeInHand, bool concentric);
    // 主 2D 视窗上的左键点击（离线取点）：填进像素输入框并立刻重算
    void onMainViewPixelClicked(int x, int y);
    // 主窗口的查询结果：ok=false 时 message 是可读中文原因
    void setOnlinePixelResult(int pixelX, int pixelY, bool ok,
                              double xMm, double yMm, double zMm,
                              const QString& message);

protected:
    void showEvent(QShowEvent* event) override;
    void hideEvent(QHideEvent* event) override;

private:
    void buildUi();
    void buildDistancePage(QStackedWidget* stack);
    void buildPixelTo3DPage(QStackedWidget* stack);
    void buildCalibrationPage(QStackedWidget* stack);
    void buildTransformPage(QStackedWidget* stack);
    void buildRobotCommPage(QStackedWidget* stack);
    // 8 个方法页（顺序 = MeasureTools::methodSpecs()），共用 MeasurePage 基类。
    void buildMeasurePages(QStackedWidget* stack);
    // 左侧列表换项：切换显示页、把当前 ROI 推给新页、写一条 [测量-说明]。
    void onToolChanged(int row);
    bool activeToolIsMeasure() const;
    // 把面板持有的 ROI 矩形推给当前方法页（页里自带取点与提示）。
    void pushRoiToActivePage(const QString& note);
    QStringList roiLabels() const;
    void updateDistanceResult();
    void updatePixelTo3DResult();
    void updateCalibrationResult();
    void onCalibrationFinished();
    // 手眼标定页当前的参数（两个方法共用，行为与原来逐字一致）。
    CalibrationService::Params calibParams() const;
    // 发起一次标定（folder + 内存里的位姿行），结果走 onCalibrationFinished。
    void runCalibration(const QString& folder, const std::vector<QString>& poseLines);
    void updatePoseInputHint();
    void updateTransformResult();
    void refreshPixelTo3DImages();
    void showPixelTo3DImage(int index);
    // 在线/离线开关落到控件上：在线禁用整组文件输入并给提示，离线恢复。
    void applyPixelTo3DMode();
    // 冻结的唯一出口：面板可见(requireVisible) + 当前页是「像素→3D」+ 离线且图像有效，
    // 全满足才请求主窗口冻结，否则立刻解冻。
    void updateOfflineFreeze(bool requireVisible = true);
    // 在线模式点「计算」：解析手输像素并发 pixelTo3DOnlineQueryRequested。
    void requestOnlinePixelQuery();

    QListWidget* m_toolList = nullptr;
    QStackedWidget* m_stack = nullptr;

    // Distance tool inputs
    QLineEdit* m_p1Input = nullptr;
    QLineEdit* m_p2Input = nullptr;
    QComboBox* m_unitCombo = nullptr;
    QLabel* m_resultLabel = nullptr;
    QLabel* m_distanceHint = nullptr;
    QPushButton* m_copyBtn = nullptr;
    QPushButton* m_calcBtn = nullptr;

    // Pixel-to-3D tool inputs (offline mode)
    QLineEdit* m_p2dDir = nullptr;
    QComboBox* m_p2dImageCombo = nullptr;
    QLineEdit* m_p2dIntrinsic = nullptr;
    QLineEdit* m_p2dExtrinsic = nullptr;
    QLineEdit* m_p2dPixel = nullptr;
    QComboBox* m_p2dModeCombo = nullptr;      // p2d_mode：离线（默认）/ 在线
    QWidget* m_p2dPage = nullptr;             // 堆叠页里的「像素→3D」页（冻结判据用）
    // 在线模式下整组禁用的控件（文件输入 + 对应标签）
    QVector<QWidget*> m_p2dOfflineOnly;
    bool m_p2dOnline = false;
    QLabel* m_p2dResult = nullptr;
    QLabel* m_p2dHint = nullptr;
    QPushButton* m_p2dCopyBtn = nullptr;
    QString m_p2dResultValue;   // values only, for copy

    // Hand-eye calibration tool (offline folder)
    QLineEdit* m_calibDir = nullptr;
    QLineEdit* m_calibPoseFile = nullptr;
    QComboBox* m_calibEyeCombo = nullptr;
    QComboBox* m_calibMarkerCombo = nullptr;
    QComboBox* m_calibPoseUnitCombo = nullptr;
    QComboBox* m_calibAngleUnitCombo = nullptr;
    QCheckBox* m_calibAutoRemove = nullptr;
    QTextEdit* m_calibResult = nullptr;
    QLabel* m_calibHint = nullptr;
    QPushButton* m_calibCalcBtn = nullptr;
    QPushButton* m_calibCopyBtn = nullptr;
    QPushButton* m_calibSessionBtn = nullptr;
    QFutureWatcher<CalibrationService::Result>* m_calibWatcher = nullptr;
    // 「用当前会话」的状态：非空时「计算」用内存里的位姿；编辑两个路径输入框即清掉。
    QString m_sessionFolder;        // 会话目录（用当前会话时的文件夹）
    std::vector<QString> m_sessionPoses;  // 会话位姿（顺序 = 采集顺序）
    bool m_sessionActive = false;   // true = 当前处于「用当前会话」模式

    // Coordinate-transform tool inputs (text-paste based)
    QComboBox* m_mountCombo = nullptr;
    QLineEdit* m_matInput = nullptr;
    QLineEdit* m_camPointInput = nullptr;
    QComboBox* m_camUnitCombo = nullptr;
    QWidget* m_poseGroup = nullptr;
    QLineEdit* m_poseInput = nullptr;
    QComboBox* m_poseUnitCombo = nullptr;
    QComboBox* m_poseFormatCombo = nullptr;
    QComboBox* m_angleUnitCombo = nullptr;
    QLabel* m_rotDescLabel = nullptr;
    QLabel* m_transformHint = nullptr;
    QLabel* m_transformResult = nullptr;
    QPushButton* m_transformCalcBtn = nullptr;
    QPushButton* m_transformCopyBtn = nullptr;
    QString m_transformValues;  // last computed base coords (values only)

    // Robot communication tool (Modbus TCP / UR Realtime)
    QComboBox* m_robotProtocol = nullptr;
    QLineEdit* m_robotHost = nullptr;
    QSpinBox* m_robotPort = nullptr;
    QWidget* m_modbusFieldsWidget = nullptr;   // Modbus-only rows (hidden for UR)
    QSpinBox* m_robotStartAddr = nullptr;
    QComboBox* m_robotFormat = nullptr;
    QLineEdit* m_robotScale = nullptr;
    QSpinBox* m_robotUnitId = nullptr;
    QPushButton* m_btnRobotConnect = nullptr;
    QPushButton* m_btnRobotSimulate = nullptr;
    QLabel* m_robotStatus = nullptr;
    QCheckBox* m_robotAutoReadCheck = nullptr;

    // ── Measurement tools (3D 测量一体化工具 parity) ──
    // 8 个方法页，左侧列表里各占一项。面板只留三样共享状态：点云、ROI 矩形、
    // 重复性序列库；结果表 / 偏差图 / 快照都由各页自己发布（MeasurePage）。
    std::vector<MeasurePage*> m_pages;
    MeasurePage* m_page = nullptr;      // 最近一次显示的方法页（切到别的工具后仍指向它）
    int m_firstMeasureRow = 0;          // 左侧列表里第一个测量方法所在的行
    bool m_measureActive = false;       // 当前列表项是不是测量方法

    FrameBuffer::DoubleBuf m_measureGrid;
    int m_measureGridW = 0;
    int m_measureGridH = 0;
    int m_imageW = 0;
    int m_imageH = 0;
    QVector<QRect> m_roiRects;                 // image pixels, max 2
    QMap<QString, QVector<double>> m_series;   // repeatability series (memory only)
};
