#pragma once

#include <QDialog>
#include <QListWidget>
#include <QStackedWidget>
#include <QCheckBox>
#include <QComboBox>
#include <QImage>
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
class AppConfig;
class RobotProgramController;
class RobotProgramPanel;
class QFormLayout;
class QGroupBox;

// Non-modal tools panel (v2.0).  Left: tool list.  Right: the selected tool.
// Tools: Euclidean distance, coordinate transform (walk-point validation), and
// one entry per measurement method (P3) sharing a single MeasurePage base.
class ToolsPanel : public QDialog {
    Q_OBJECT
public:
    explicit ToolsPanel(QWidget* parent = nullptr);

    // 主窗口把自己的 AppConfig 借给本页（唯一写入者仍是主窗口持有的那一份实例，
    // 避免两个 AppConfig 各存一份 m_data 互相覆盖）。必须在 show 前调用。
    void setAppConfig(AppConfig* cfg);

    // 机器人控制台的控制端由主窗口创建后晚绑定（ToolsPanel 构造时它还不存在）。
    void setRobotProgramController(RobotProgramController* controller);

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
    // T-012：与那次拍照同一帧的 2D 图像（亚像素边缘用）。单独入口，上面那个签名不变。
    void setMeasurementImage(const QImage& image);
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
    // 离线模式且当前工具页就是「像素→3D」：主窗口据此把主 2D 点击只交给
    // 离线反投影，而**不再**顺带跑在线取点/填相机目标点卡片。
    bool offlinePixelTo3DActive() const
    {
        return !m_p2dOnline && m_stack != nullptr && m_p2dPage != nullptr
            && m_stack->currentWidget() == m_p2dPage;
    }
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
    // 主窗口回答：folder = 当前会话目录；三列按采集顺序一一对应（相机目标点 /
    // 机器人拍照位姿 / 机器人目标点），**不做过滤**，空行即"该列这一组没有值"。
    // eyeInHand / marker / concentric 与主窗口当前选择一致，要对齐到下拉框。
    void useCurrentSession(const QString& folder,
                           const QStringList& cameraLines,
                           const QStringList& poseLines,
                           const QStringList& tcpLines,
                           bool eyeInHand, bool marker, bool concentric);
    // 主窗口换了会话（「新建会话」/ 启动建第一组）：丢掉缓存的三列与目录。
    // 不丢的话「计算」会拿上一组的位姿算出这一组的结果 —— 数据是错的，界面看不出来。
    void clearSessionData();
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
    void buildFormatInferencePage(QStackedWidget* stack);
    void buildRobotCommPage(QStackedWidget* stack);
    // 机器人控制台（程序节点 + 点动）。独立一项，不塞进「机器人通信」页。
    void buildRobotProgramPage(QStackedWidget* stack);
    // 7 个方法页（顺序 = MeasureTools::methodSpecs()），共用 MeasurePage 基类。
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
    // 手眼标定页当前的参数（含标定方式；两个方法共用）。
    CalibrationService::Params calibParams() const;
    // 凑齐一次标定要的三列数据：优先「用当前会话」的内存三列，否则按路径读文件。
    // 失败时写 m_calibHint 并返回 false。顺序敏感 —— 路径输入框的 textChanged 会
    // 清掉会话状态，所以这里必须先判会话、再碰输入框。
    // errorOut（可选）：失败原因原样返回，供推算页在自己的提示行显示；
    // 标定页仍然写 m_calibHint，两处不各写一份文案。
    bool gatherCalibrationInput(QString& folder,
                                std::vector<QString>& cameraLines,
                                std::vector<QString>& poseLines,
                                std::vector<QString>& tcpLines,
                                QString* errorOut = nullptr);
    // 按标定方式 + 安装方式决定哪几行输入框要看得到：
    //   标定板            → 位姿文件、标定板类型、位姿单位
    //   戳点 + 眼在手上   → 位姿文件、相机点位文件、戳点文件、位姿单位
    //   戳点 + 眼在手外   → 相机点位文件、戳点文件（没有机器人拍照位姿这一列）
    void updateCalibrationModeVisibility();
    // 下拉框里当前选的格式 / 角度单位（Id 存在 itemData 里，不靠索引）。
    RobotDataFormats::Id currentCalibPoseFormat() const;
    TransformTools::AngleUnit currentCalibAngleUnit() const;
    // 刷新「位姿格式」下面那行说明：该格式是什么 + 是否已应用为全局预设。
    void updateCalibFormatHint();
    // 「应用」：写进 AppConfig 预设（主界面「计算」读它）。
    void applyCalibPoseFormat();
    // 「试算各格式」：当前三列数据把 5 种常见格式 x 度/弧度 各算一遍，按总平均误差排序。
    void runTryAllPoseFormats();
    void onTryAllFinished();
    // 机器人数据格式推算：把 1~3 组点动前后位姿喂给 RobotDataFormats 的推断器。
    void updateFormatInference();
    // 方式 ③ 的数据来源提示（当前会话 / 标定页文件夹 / 尚未选择）。
    void updateInferenceDataLabel();
    // 推算结果唯一时，把它写成全局预设（标定页/主界面计算都按它）。
    void applyInferredFormat();
    // 发起一次标定（folder + 内存里的三列），结果走 onCalibrationFinished。
    void runCalibration(const QString& folder,
                        const std::vector<QString>& cameraLines,
                        const std::vector<QString>& poseLines,
                        const std::vector<QString>& tcpLines);
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
    RobotProgramPanel* m_robotProgramPage = nullptr;

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
    QFormLayout* m_calibForm = nullptr;
    QLineEdit* m_calibDir = nullptr;
    QComboBox* m_calibTypeCombo = nullptr;   // 标定板识别 / 戳点标定
    QLineEdit* m_calibPoseFile = nullptr;
    QLineEdit* m_calibCameraFile = nullptr;  // 戳点标定：相机目标点
    QLineEdit* m_calibTcpFile = nullptr;     // 戳点标定：机器人目标点（戳点）
    // 文件行的容器（行内是输入框 + 「浏览」按钮）；按下标方式显隐整行。
    QWidget* m_calibPoseFileRow = nullptr;
    QWidget* m_calibCameraFileRow = nullptr;
    QWidget* m_calibTcpFileRow = nullptr;
    // 在数据文件夹里挑一个 txt，写回文件名；文件在别的目录时连同文件夹一起改。
    void chooseCalibrationFile(QLineEdit* edit, const QString& title);
    QComboBox* m_calibEyeCombo = nullptr;
    QComboBox* m_calibMarkerCombo = nullptr;
    QComboBox* m_calibPoseUnitCombo = nullptr;
    QComboBox* m_calibAngleUnitCombo = nullptr;
    QComboBox* m_calibFormatCombo = nullptr;   // 卡片里 3 个旋转数怎么读
    QCheckBox* m_calibAdvancedCheck = nullptr; // 显示首尾同轴的 12 种
    QWidget* m_calibFormatRow = nullptr;       // 上面那行的容器（显隐用）
    QLabel* m_calibFormatLabel = nullptr;      // 该格式的说明 + 是否已应用
    QPushButton* m_calibApplyBtn = nullptr;    // 写进 AppConfig 预设（主界面也读它）
    QCheckBox* m_calibAutoRemove = nullptr;
    QTextEdit* m_calibResult = nullptr;
    QLabel* m_calibHint = nullptr;
    QPushButton* m_calibCalcBtn = nullptr;
    QPushButton* m_calibCopyBtn = nullptr;
    QPushButton* m_calibSessionBtn = nullptr;
    QFutureWatcher<CalibrationService::Result>* m_calibWatcher = nullptr;
    // 「试算各格式」用独立 watcher：多次标定不能和普通计算共用一个 future。
    // 现在由「机器人数据格式推算」页触发（数据仍取自本页/当前会话）。
    QFutureWatcher<QString>* m_calibTryAllWatcher = nullptr;
    AppConfig* m_config = nullptr;
    // 「用当前会话」的状态：非空时「计算」用内存里的数据；编辑路径输入框即清掉。
    QString m_sessionFolder;              // 会话目录（用当前会话时的文件夹）
    std::vector<QString> m_sessionPoses;  // 机器人拍照位姿（顺序 = 采集顺序）
    std::vector<QString> m_sessionCamera; // 相机目标点（顺序 = 采集顺序）
    std::vector<QString> m_sessionTcp;    // 机器人目标点（顺序 = 采集顺序）
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
    QCheckBox* m_advancedFormatsCheck = nullptr;  // 显示首尾同轴的高级格式
    QComboBox* m_angleUnitCombo = nullptr;
    QLabel* m_rotDescLabel = nullptr;
    QLabel* m_transformHint = nullptr;
    QLabel* m_transformResult = nullptr;
    QPushButton* m_transformCalcBtn = nullptr;
    QPushButton* m_transformCopyBtn = nullptr;
    QString m_transformValues;  // last computed base coords (values only)

    // 机器人数据格式推算页
    QWidget* m_inferPage = nullptr;
    QComboBox* m_inferMethodCombo = nullptr;  // ① 基坐标点动 / ② 工具坐标点动 / ③ 标定残差
    QComboBox* m_inferUnitCombo = nullptr;
    QWidget* m_inferUnitRow = nullptr;        // 方式 ③ 不看角度单位，整行藏起来
    QWidget* m_inferExperiments = nullptr;    // 方式 ①② 显示，③ 隐藏
    std::array<QComboBox*, 3> m_inferAxis {}; // 这一组实际绕哪根轴点的
    std::array<QLineEdit*, 3> m_inferBefore {};
    std::array<QLineEdit*, 3> m_inferAfter {};
    // 方式 ③：把「试算各格式」从标定页迁到这里，数据仍沿用标定页的设置/来源。
    QWidget* m_inferResidualGroup = nullptr;
    QLabel* m_inferDataLabel = nullptr;
    QPushButton* m_inferSessionBtn = nullptr;
    QPushButton* m_inferTryAllBtn = nullptr;
    // 方式 ③ 的输入组：与手眼标定页同一批控件值（双向同步），在这里就能选文件、
    // 跑试算，不必来回切页。真正的计算仍走 gatherCalibrationInput/runTryAll。
    QFormLayout* m_inferDataForm = nullptr;
    QGroupBox* m_inferDataGroup = nullptr;
    QLineEdit* m_inferDirEdit = nullptr;
    QLineEdit* m_inferPoseFileEdit = nullptr;
    QLineEdit* m_inferCameraFileEdit = nullptr;
    QLineEdit* m_inferTcpFileEdit = nullptr;
    QWidget* m_inferPoseFileRow = nullptr;
    QWidget* m_inferCameraFileRow = nullptr;
    QWidget* m_inferTcpFileRow = nullptr;
    QComboBox* m_inferCalibTypeCombo = nullptr;
    QComboBox* m_inferEyeCombo = nullptr;
    QComboBox* m_inferMarkerCombo = nullptr;
    QComboBox* m_inferPoseUnitCombo = nullptr;
    QCheckBox* m_inferAutoRemoveCheck = nullptr;
    // 推算页「推算 / 应用为全局预设」那一行：方法 ①② 显示，③ 隐藏。
    QWidget* m_inferActionRow = nullptr;
    // 按推算页自己的标定方式/安装方式显隐输入行（与标定页同一套规则）。
    void updateInferenceInputVisibility();
    // 「用当前会话」是从推算页点的：载入后直接跑试算，不再白跑一次普通标定。
    bool m_sessionForTryAll = false;
    QLabel* m_inferHint = nullptr;
    QTextEdit* m_inferResult = nullptr;
    QPushButton* m_inferRunBtn = nullptr;
    QPushButton* m_inferApplyBtn = nullptr;
    // 唯一判定时记住它，供「应用为全局预设」；否则保持无效。
    RobotDataFormats::Id m_inferBest = RobotDataFormats::Id::EulerSxyz;
    bool m_inferBestValid = false;
    TransformTools::AngleUnit m_inferBestUnit = TransformTools::AngleUnit::Degree;

    // Robot communication tool (Modbus TCP / UR Realtime)
    QComboBox* m_robotProtocol = nullptr;
    QLineEdit* m_robotHost = nullptr;
    // 埃夫特专用：输入里带了 ":端口" 时显示一行说明（平时隐藏）。
    QLabel* m_robotHostNote = nullptr;
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
    // 7 个方法页，左侧列表里各占一项。面板只留三样共享状态：点云、ROI 矩形、
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
    QImage m_measureImage;                     // 本次拍照的 2D 图像（亚像素边缘用）
    QVector<QRect> m_roiRects;                 // image pixels, max 2
    QMap<QString, QVector<double>> m_series;   // repeatability series (memory only)
};
