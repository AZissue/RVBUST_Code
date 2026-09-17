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

// Non-modal tools panel (v2.0).  Left: tool list.  Right: the selected tool.
// Tools: Euclidean distance, coordinate transform (walk-point validation).
class ToolsPanel : public QDialog {
    Q_OBJECT
public:
    explicit ToolsPanel(QWidget* parent = nullptr);

    void setRobotStatus(const QString& text, bool ok);
    void setRobotConnected(bool connected);

    // ── Measurement page (aligned with the Python 3D 测量一体化工具) ──
    // The 3D grid of the last capture, handed over by refcount.  The image size
    // is needed because the dragged ROI is in image pixels while the grid is in
    // point-map cells — the two do not have to share a resolution.
    void setMeasurementCloud(const FrameBuffer::DoubleBuf& grid, int gridW, int gridH,
                             int imageW, int imageH);
    // A rectangle dragged on the 2D view (image pixels).
    void onRoiSelected(const QRect& rect);
    void clearMeasurementRois();
    // Mirror of the 3D view's toolbar toggle.  Applying it re-runs the last
    // measurement so the colouring appears (or disappears) immediately.
    void setDeviationColoring(bool on);

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

private:
    void buildUi();
    void buildDistancePage(QStackedWidget* stack);
    void buildPixelTo3DPage(QStackedWidget* stack);
    void buildCalibrationPage(QStackedWidget* stack);
    void buildTransformPage(QStackedWidget* stack);
    void buildRobotCommPage(QStackedWidget* stack);
    void buildMeasurePage(QStackedWidget* stack);
    void refreshRoiPoints();
    // Drops the *result* state (table rows, deviation map, annotations, 3D
    // payload) while keeping the repeatability series — that accumulator is
    // meant to survive across captures, everything else refers to one frame.
    void resetMeasurementState();
    void runMeasurement();
    void addLastToRepeatSeries();
    void refreshSeriesUi();
    Measurement::Snapshot buildSnapshot() const;
    void updateMeasureHint();
    QStringList roiLabels() const;
    void updateDistanceResult();
    void updatePixelTo3DResult();
    void updateCalibrationResult();
    void onCalibrationFinished();
    void updatePoseInputHint();
    void updateTransformResult();
    void refreshPixelTo3DImages();
    void showPixelTo3DImage(int index);

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
    class Image2DView* m_p2dView = nullptr;
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
    QFutureWatcher<CalibrationService::Result>* m_calibWatcher = nullptr;

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

    // ── Measurement tool (3D 测量一体化工具 parity) ──
    QLabel* m_measureCloudLabel = nullptr;
    QLabel* m_measureRoiLabel = nullptr;
    QLabel* m_measureHint = nullptr;
    QComboBox* m_measureMethod = nullptr;
    QCheckBox* m_tolEnable = nullptr;
    QDoubleSpinBox* m_tolLo = nullptr;
    QDoubleSpinBox* m_tolHi = nullptr;
    QPushButton* m_measureBtn = nullptr;
    QPushButton* m_repeatAddBtn = nullptr;
    QPushButton* m_roiClearBtn = nullptr;
    QCheckBox* m_devColor3d = nullptr;   // paint the ROI on the 3D cloud too (P4)
    QTableWidget* m_measureTable = nullptr;
    QComboBox* m_seriesCombo = nullptr;
    QLabel* m_seriesSummary = nullptr;

    FrameBuffer::DoubleBuf m_measureGrid;
    int m_measureGridW = 0;
    int m_measureGridH = 0;
    int m_imageW = 0;
    int m_imageH = 0;
    QVector<QRect> m_roiRects;                       // image pixels, max 2
    std::vector<MeasureTools::Vec3> m_roiPoints[2];  // extracted per ROI
    std::vector<std::size_t> m_roiCells[2];          // matching grid cell indices
    // Display payload of the last measurement.
    QVector<Measurement::DevSample> m_devSamples;
    double m_devLo = 0.0, m_devHi = 0.0;
    bool m_devRobust = false;
    int m_devClipped = 0;
    bool m_snapshotCoolWarm = true;   // colormap choice of the last deviation map
    QVector<Measurement::Annotation> m_annotations;
    std::vector<std::array<double, 2>> m_section;
    double m_sectionStep = 0.0;
    QVector<Measurement::ResultRow> m_lastRows;
    QString m_lastKey;             // "方法/输出" of the primary value
    double m_lastPrimary = 0.0;
    bool m_hasLast = false;
    QString m_pageFooter;
    // 3D payload (P4): per-point colour for the captured cloud plus the fitted
    // plane and ROI box the view annotates.  The colour array is shared, not
    // copied, on every snapshot hand-off — see Measurement::Snapshot.
    std::shared_ptr<const std::vector<std::array<float, 3>>> m_cloudColors;
    bool m_hasPlane = false;
    std::array<double, 3> m_planePoint{};
    std::array<double, 3> m_planeNormal{};
    bool m_hasBox = false;
    std::array<double, 3> m_boxMin{};
    std::array<double, 3> m_boxMax{};
    QMap<QString, QVector<double>> m_series;   // repeatability series (memory only)
};
