#pragma once

// ── 测量帧（阶段 27）：把"一次测量"完整落盘，并原样读回 ──────────────
//
// 3.0 规划 M-02 要求真件可回放，否则改算法就是在没有标尺的情况下调参
// （2026-10 的 P1 正是"合成 32 场景全绿、真机一跑就废"）。测量页手里其实
// 已经有全部证据，只是从来没落过盘：
//
//   frame.grid   组织化点云网格，**与 tests/measure_truth 的 .grid 字节同构**：
//                ASCII 头 "<w> <h>\n" + w*h*3 个小端 float32（x,y,z）mm，
//                行主序（cell = y*w + x），无效单元为 NaN。所以现场的帧可以直接
//                喂给 measure_truth 的读取链路，不需要转换脚本。
//   frame.png    同一次拍照的 2D 图像（亚像素边缘要用）。
//   frame.json   方法、ROI 矩形（图像像素）、结果行、口径（extra）与时间。
//
// frame.json **最后写**：中途失败的目录没有清单，load() 读不出来，因此不会
// 留下"看起来像一帧、其实是半截"的数据。
//
// 这里只做文件 I/O 与格式校验，没有任何界面依赖；单测用临时目录验证往返、
// 尺寸不符、网格头非法、NaN 保留等，见 tests/test_measure_frame.cpp。
#include <QDateTime>
#include <QImage>
#include <QJsonObject>
#include <QString>
#include <QVector>

#include <vector>

namespace MeasureFrame {

inline const char* kManifestName = "frame.json";
inline const char* kGridName = "frame.grid";
inline const char* kImageName = "frame.png";
inline const char* kSchema = "handeye.measure_frame/1";

// 一轮测量在结果表里的那一行（与 Measurement::ResultRow 同义；这里不 include
// 界面头，逻辑层保持可单独编译）。
struct ResultRow {
    QString method;
    QString value;
    QString unit;
    QString confidence;
    int points = 0;
};

// 图像像素矩形（含端点），与 QRect 的 left/top/right/bottom 一致。
struct RoiRect {
    int left = 0;
    int top = 0;
    int right = 0;
    int bottom = 0;
    bool valid() const { return right > left && bottom > top; }
};

struct Manifest {
    QString schema = QString::fromLatin1(kSchema);
    QString methodId;      // MeasureTools::methodId()，例如 "hole3d"
    QString capturedAt;    // ISO-8601（save() 负责填）
    QString note;          // 一行上下文（点云规模 / ROI 提示）
    int gridW = 0;
    int gridH = 0;
    bool hasImage = false;
    int imageW = 0;
    int imageH = 0;
    QVector<RoiRect> rois;
    QVector<ResultRow> rows;
    QString primaryKey;    // 主值对应的结果行 method
    double primaryValue = 0.0;
    bool hasPrimary = false;
    // 该方法的专有口径（覆盖率、圆度、是否亚像素…）。键名由页面自己定，
    // 这里不解释；回放/报告只需要原样保留。
    QJsonObject extra;
};

// 写一帧到 dir（目录不存在则创建）。grid 必须是 w*h*3 个有限/NaN 的 double。
// 出错时返回 false 并写 *error（中文，可直接上屏）。
bool save(const QString& dir, const Manifest& manifest,
          const std::vector<double>& grid, const QImage& image,
          QString* error = nullptr);

// 从 dir 读回一帧。清单、网格头与文件长度必须互相一致，否则拒绝。
bool load(const QString& dir, Manifest* manifest, std::vector<double>* grid,
          QImage* image, QString* error = nullptr);

// 默认目录名：<root>/measure_frames/<method>_<yyyyMMdd_HHmmss>。
// methodId 里只保留 [A-Za-z0-9_]，其余字符换成 '_'（方法 id 本来就是 ASCII）。
QString suggestDir(const QString& root, const QString& methodId, const QDateTime& when);

// 网格文件里的一帧：读取（供回放工具与单测共用）。
bool readGrid(const QString& path, int* w, int* h, std::vector<double>* grid,
              QString* error = nullptr);
bool writeGrid(const QString& path, const std::vector<double>& grid, int w, int h,
               QString* error = nullptr);

} // namespace MeasureFrame
