#pragma once

// ── 测量页基类（第 7 回合 P3）───────────────────────────────────────────
//
// 用户第 2、3 条要求"每个测量方法都可以单独设置出来，设计成一个单独的工具"，
// 并且"目前支持两个 ROI A/B，有些方法只用一个或多个，你看是否需要单独做个
// 限制；清除 ROI 可以放到视窗工具栏"。
//
// 于是把测量页拆成 7 个独立页（左侧列表各占一项，见 MeasurePages.cpp；「3D 孔洞」
// 把原圆环拟合与孔径合并成一页，并按 2.html 自绘界面），它们
// **共用本基类**里的四件事——这四件事以前是一个 700 行 switch 里的共享变量：
//
//   * ROI：像素矩形 -> 网格取点（走 MeasureTools::roiImageToGrid +
//     pointsInRoiIndexed，与校验工装同一条链路），按 spec 的 roiCount 限制与提示；
//   * 结果表：5 列（方法/数值/单位/点数/可信度）的填充与主值记录；
//   * 重复性序列：combo / 统计 / 清空，序列库由面板持有（跨页共用，跨帧累积）；
//   * 快照发布：把偏差图/尺寸总图/截面/3D 载荷装进 Measurement::Snapshot 发出去，
//     既有链路（3D 偏差着色、四个显示页签、ROI 叠加）完全不变。
//
// 子类只写 compute()：本方法自己的算法 + 自己那几行结果 + 自己的显示载荷。
#include <QImage>
#include <QMap>
#include <QRect>
#include <QString>
#include <QVector>
#include <QWidget>

#include <array>
#include <vector>

#include "logic/FrameBuffer.h"
#include "logic/MeasureMethods.h"
#include "logic/MeasureTools.h"
#include "ui/MeasurementSnapshot.h"

class QLabel;
class QPushButton;
class QCheckBox;
class QDoubleSpinBox;
class QTableWidget;
class QComboBox;

// 一次测量的输入与输出。子类只碰这个结构，不碰界面控件——结果的排版、可信度
// 标签、偏差色标、快照组装都由基类统一做，所以 7 个方法的显示行为必然一致。
struct MeasureContext {
    // ── 输入（基类已按 ROI 取好点）──
    const std::vector<MeasureTools::Vec3>* roi = nullptr;       // roi[0], roi[1]
    const std::vector<std::size_t>* roiCells = nullptr;         // 对应的网格单元号
    const QVector<QRect>* roiRects = nullptr;                   // 图像像素矩形
    int gridW = 0;
    int gridH = 0;
    // T-012：亚像素边界要找图像灰度的边缘，所以把这一帧的图像（灰度视图）与
    // 整个 3D 网格也交给子类（网格用于"从 ROI 往外长材料区"找外缘）。
    const MeasureTools::GrayImage* image = nullptr;
    const std::vector<double>* grid = nullptr;

    // ── 输出：结果表 ──
    std::vector<Measurement::ResultRow> rows;
    QString primaryKey;          // 主值（供「加入重复性」累积）
    double primaryValue = 0.0;
    bool hasPrimary = false;
    QString refusal;             // 非空 = 这次跑不了，直接显示这句并停
    QString footer;              // 无偏差图时页面底部的说明行
    QString confidenceNote;      // 可信度的补充口径，如"扇区覆盖 34/36"

    // ── 输出：显示载荷（偏差图 / 截面 / 3D 标注）──
    bool hasDeviation = false;
    std::vector<double> devValues;             // 与 devCells 等长
    std::vector<std::size_t> devCells;
    bool devCoolWarm = true;                   // false = turbo（轮廓/圆周类）
    MeasureTools::Plane plane;
    bool hasPlane = false;
    std::array<double, 3> planePoint{};
    std::array<double, 3> planeNormal{};
    bool hasBox = false;
    std::array<double, 3> boxMin{};
    std::array<double, 3> boxMax{};
    bool hasSection = false;
    std::vector<std::array<double, 2>> section;   // (距离, 高度)
    double sectionStep = 0.0;
    std::vector<Measurement::Annotation> annotations;
};

class MeasurePage : public QWidget {
    Q_OBJECT
public:
    explicit MeasurePage(MeasureTools::Method method, QWidget* parent = nullptr);

    MeasureTools::Method method() const { return m_spec.method; }
    const MeasureTools::MethodSpec& spec() const { return m_spec; }
    int roiCount() const { return m_spec.roiCount; }

    // 面板交接：一帧点云（网格 + 尺寸 + 图像尺寸）。
    void setCloud(const FrameBuffer::DoubleBuf& grid, int gridW, int gridH,
                  int imageW, int imageH, const QString& cloudText);
    // T-012：与 setCloud 同一次拍照的那张 2D 图像（亚像素边缘用）。单独一个入口，
    // setCloud 的签名保持不变。非灰度格式在这里转成 8bit 灰度存起来。
    void setImage(const QImage& image);
    // ROI 矩形（图像像素）。基类按 spec 的 roiCount 取点；多余的框会被忽略。
    // `note` 是面板按 planRoiDrag/roiStateText 得出的那一句提示（P3.2）。
    void setRoiRects(const QVector<QRect>& rects, const QString& note);
    // 重复性序列库由面板持有：跨页共用、跨帧累积。
    void setSeriesStore(QMap<QString, QVector<double>>* store);
    // 3D 偏差着色开关的双向同步（面板 / 3D 工具栏）。只同步勾选状态；要立刻
    // 看到效果由调用方决定（rerun()），免得一次点击触发 7 页各自重算。
    // 自绘界面的页（3D 孔洞）没有基类的勾选框，所以这两个入口是虚函数。
    virtual void setDeviationColoring(bool on);
    bool deviationColoring() const;
    // 用当前 ROI 重算上一次的结果（不写新的 [测量-结果]）：改着色开关时用。
    // 自绘界面重写它来把重算后的数值重新画到结果面板。
    virtual void rerun();
    // 新的一帧 / 新一轮测量：清掉结果与显示载荷（重复性序列不动）。
    // 自绘界面重写它来把结果面板复位成「等待测量」。
    virtual void resetResult();
    // 面板切换工具项时调用：写一条 [测量-说明]。
    QString explainLine() const;
    Measurement::Snapshot snapshot() const;
    void refreshSeriesUi();

signals:
    void snapshotReady(const Measurement::Snapshot& snapshot);
    void deviationColoringChanged(bool on);
    void clearRoiRequested();
    void logRequested(const QString& line);
    // ROI 选择变化（自定义界面的页用它刷新「测量区域」等显示）。
    void roiChanged();

protected:
    // 自绘界面的页（3D 孔洞）用：跳过基类的表单/结果表/序列区，
    // 只保留 ROI 取点、算法调用与快照发布。子类自己建控件、自己显示结果。
    MeasurePage(MeasureTools::Method method, bool buildGenericUi,
                QWidget* parent);
    void runMeasurement(bool logResult = true);

    // 子类唯一的算法入口。基类已经保证 ROI 够用。
    virtual void compute(MeasureContext& ctx) = 0;

    // 自绘界面读取最近一次 runMeasurement() 的结果。
    bool hasResult() const { return m_hasResult; }
    double primaryValue() const { return m_primaryValue; }
    QString primaryKey() const { return m_primaryKey; }
    QString lastHintText() const { return m_lastHint; }
    // 自绘界面的公差（写进快照，3D 着色/趋势与其他页一致）。
    void setCustomTolerance(bool enabled, double lo, double hi);

    // 给子类用的小工具（与旧面板同一套口径）。
    static QString confidenceFor(int points, double rms);
    static QString fmt4(double v);
    QString roiText(int slot) const;   // "ROI A: (x0,y0)-(x1,y1)，1234 点"
    // 自绘界面画「探测位置边界」用：ROI 内已取好的 3D 点与图像像素矩形。
    const std::vector<MeasureTools::Vec3>& roiPoints(int slot) const;
    QRect roiRectPx(int slot) const;
    // 重复性序列库（跨页共用、仅内存）。自绘界面把主值直接写进去，
    // 「重复性」页仍能统计它。
    QMap<QString, QVector<double>>* seriesStore() const { return m_series; }
    // 重复性页要读的当前序列（序列库在基类手里，跨页共用）。
    QString currentSeriesName() const;
    const QVector<double>* currentSeries() const;
    // applyDeviation() 用它判断要不要生成 3D 着色点云（自绘界面重写）。
    virtual bool wantsDeviationColors() const;

    double m_devLo = 0.0;
    double m_devHi = 0.0;
    QString m_lastHint;
    bool m_customTolEnabled = false;
    double m_customTolLo = -0.05;
    double m_customTolHi = 0.05;

private:
    void buildUi();
    void run(bool logResult = true);
    void publish();
    void showHint(const QString& text, bool error = true);
    void applyDeviation(MeasureContext& ctx);
    void onRepeatAdd();
    void clearSeries();

    MeasureTools::MethodSpec m_spec{};
    FrameBuffer::DoubleBuf m_grid;
    int m_gridW = 0;
    int m_gridH = 0;
    int m_imageW = 0;
    int m_imageH = 0;
    std::vector<unsigned char> m_gray;   // 本次拍照的 8bit 灰度图像（行主序）
    int m_grayW = 0;
    int m_grayH = 0;
    QVector<QRect> m_rects;

    std::vector<MeasureTools::Vec3> m_pts[2];
    std::vector<std::size_t> m_cells[2];

    // 结果与显示载荷（本页私有：7 个页各有一份，互不干扰）
    std::vector<Measurement::ResultRow> m_rows;
    QString m_primaryKey;
    double m_primaryValue = 0.0;
    bool m_hasPrimary = false;
    int m_primaryIndex = -1;     // 主值在结果表里的行号（[测量-结果] 取它的点数与可信度）
    bool m_hasResult = false;
    QString m_footer;
    QVector<Measurement::DevSample> m_devSamples;
    bool m_devRobust = false;
    int m_devClipped = 0;
    bool m_devCoolWarm = true;
    QVector<Measurement::Annotation> m_annotations;
    std::vector<std::array<double, 2>> m_section;
    double m_sectionStep = 0.0;
    std::shared_ptr<const std::vector<std::array<float, 3>>> m_cloudColors;
    bool m_hasPlane = false;
    std::array<double, 3> m_planePoint{};
    std::array<double, 3> m_planeNormal{};
    bool m_hasBox = false;
    std::array<double, 3> m_boxMin{};
    std::array<double, 3> m_boxMax{};

    QMap<QString, QVector<double>>* m_series = nullptr;

    QLabel* m_cloudLabel = nullptr;
    QLabel* m_roiReqLabel = nullptr;
    QLabel* m_roiLabel = nullptr;
    QLabel* m_roiNote = nullptr;
    QLabel* m_hint = nullptr;
    QTableWidget* m_table = nullptr;
    QCheckBox* m_tolEnable = nullptr;
    QDoubleSpinBox* m_tolLo = nullptr;
    QDoubleSpinBox* m_tolHi = nullptr;
    QCheckBox* m_devColorBox = nullptr;
    QPushButton* m_runBtn = nullptr;
    QPushButton* m_repeatAddBtn = nullptr;
    QPushButton* m_roiClearBtn = nullptr;
    QComboBox* m_seriesCombo = nullptr;
    QLabel* m_seriesSummary = nullptr;
};
