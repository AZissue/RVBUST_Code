#pragma once

// ── 测量方法目录（第 7 回合 P3/P4）─────────────────────────────────────
//
// 一个方法的"元信息"只有三块：它是谁（id/名字）、它需要几个 ROI、以及它的
// 说明文案。三块都放在这里，作为**纯数据**，因为其中两块是会被用户直接踩到
// 的功能，而不是界面上的装饰：
//
//   * ROI 需求 —— 一个算法需要两个 ROI 而界面只让画一个，得到的是"沉默的错
//     答案"而不是布局问题。所以它是数据，可被单测断言（tests/test_measure_methods.cpp）；
//   * 说明文案 —— 用户的原话是"怎么用、说明了什么并不清楚"，所以每个方法必须
//     自带 用途 / ROI 怎么画 / 输出含义与单位 / 可信度怎么读 / 常见错法，
//     并且选中时与测完后各写一条操作日志（见 methodExplainLine / resultLine）。
//
// 不依赖 Qt：表里的字符串是 UTF-8 的 `const char*`，界面侧用 QString::fromUtf8
// 转换，单测侧直接用 std::string 断言。
#include <cstddef>
#include <string>
#include <vector>

#include "logic/MeasureTools.h"

namespace MeasureTools {

struct MethodSpec {
    Method method;
    const char* id;          // == methodId(method)：日志与测试用的稳定 ASCII
    const char* name;        // 左侧工具列表项 / 页面标题
    int roiCount;            // == roiCountFor(method)：2 = 基准+被测，1 = 单个，0 = 不需要
    const char* roiA;        // ROI A 的角色名（roiCount < 1 时为 nullptr）
    const char* roiB;        // ROI B 的角色名（roiCount < 2 时为 nullptr）

    // ── P4 说明 ──
    const char* purpose;     // 用途：这个方法回答什么问题
    const char* howTo;       // ROI 怎么画
    const char* outputs;     // 每个输出项的含义与单位
    const char* confidence;  // 可信度怎么读
    const char* pitfalls;    // 常见错法
    const char* convention;  // 本次结果的"口径"（写进 [测量-结果]）
};

// 左侧列表的顺序即本表顺序（与 Method 枚举一致）。
inline const MethodSpec* methodSpecs(int& count)
{
    static const MethodSpec table[] = {
        { Method::Flatness, "flatness", "平面度", 1, "被测面", nullptr,
          "看一个面平不平：拟合一个基准平面，给出面上最高点与最低点之差。",
          "只在被测的那一个面上拖一个 ROI A，别跨到台阶、孔或别的面上。",
          "最小区域 PV = 最高−最低（mm，判定用这个）；LSQ PV / RMS = 最小二乘的参考值（mm）；"
          "倾斜角 = 这个面相对视线的倾斜（°）。",
          "点数越多越稳；报告值已按 MAD 剔除粗大点，单个毛刺不会撑大 PV；点数很少时只看趋势。",
          "ROI 跨了两个不同高度的面、或框进孔里的空点，PV 会明显变大。",
          "PV = 最大偏差 − 最小偏差；最小区域 MZ ≤ LSQ PV；凸起为正（朝向相机）" },

        { Method::StepHeight, "step_height", "高度段差", 2, "基准面", "被测面",
          "量两个平行面之间的高度差（台阶、段差）。",
          "先拖 ROI A 框住基准面，再拖 ROI B 框住被测面；两块都要在同一幅点云里。",
          "高度 = 被测面相对基准面的中位数偏移（mm）；RMS = 被测面点的离散（mm）。",
          "看两块的点数与 RMS：RMS 越接近平面度越好；某个面点数太少时不要采信。",
          "ROI 框到台阶侧壁或斜面上，高度会被侧壁拉偏；两个面不平行时这个高度只是近似。",
          "凸起为正：被测面朝向相机时高度为正；取中位数并剔除粗大点" },

        { Method::PlanePair, "plane_pair", "面面距离夹角", 2, "面 A", "面 B",
          "量两个面的夹角；两面接近平行时同时给出面间距离。",
          "拖 ROI A、ROI B 分别框住两个面，每块都要够大（各 3 点以上，越多越稳）。",
          "夹角（°）；两块面夹角小于 3° 时给出平行面间距（mm）。",
          "看两块的点数：都足够时才可信。夹角在 3° 附近时「间距」会时有时无，属正常。",
          "夹角大于 3° 时不报间距（两个不平行平面的「距离」没有意义），这不是测量失败。",
          "夹角取 0–90°；间距 = 面 B 到面 A 的稳健中位距离（mm）" },

        { Method::RingCircle, "ring_circle", "圆环拟合", 1, "环形材料", nullptr,
          "对一圈环形材料（圆环面、法兰环、孔口圆环）拟合一个圆，给出直径、圆心和圆度。",
          "ROI 要框住一整圈环形材料，中间是空的没关系；不要把整块矩形材料当成圆。",
          "直径 / 半径（mm）、圆心（mm）、圆度 = 半径极差（mm）。",
          "点数越多越稳；圆度接近 0 说明这一圈确实是圆，圆度很大说明框到的不是圆环。",
          "矩形 ROI 框住一个孔（孔 + 周围材料）时本法没有意义，直径会大出好几倍——"
          "要测孔径请用「孔径(孔洞边界法)」。",
          "圆 = 平面内的代数（Kåsa）最小二乘圆；圆度 = 半径最大 − 最小（mm）" },

        { Method::HoleDiameter, "hole_diameter", "孔径(孔洞边界法)", 1, "孔 + 约 2 个点距的材料", nullptr,
          "量圆孔的直径与孔心：先拟合孔所在的材料面，再沿 360° 找每个方向上最内侧的材料点，"
          "用这些孔壁点拟合圆。",
          "紧贴孔画一个近正方形的 ROI：里面是孔加上孔外约 2 个点距的材料；不要框进别的孔或台阶。",
          "直径 / 半径（mm）、圆心（mm）、圆度（mm）、扇区覆盖 = 有孔壁点的方向占比（0–1）。",
          "看扇区覆盖：覆盖 < 75% 或圆度接近半径时不可信，会标「参考」；点距越细，孔径越准。",
          "ROI 比孔大很多时，「每个方向最内侧点」变成一大片材料的统计量而不是孔壁，"
          "直径偏大且覆盖下降。",
          "取每方向最内侧材料点半径的中位数，再减半个点距做亚像素修正；覆盖按 2πR/点距 计算" },

        { Method::BoundingBox, "bounding_box", "包围盒", 1, "整个物体", nullptr,
          "量一个物体的长宽高和中心；先按 PCA 主轴对齐再量，所以摆放歪斜不会把尺寸放大。",
          "ROI 框住整个物体，六个面尽量都在里面。",
          "长 / 宽 / 高（mm，长边在前）、中心（mm）。",
          "点数越多越好；只看到一部分时，量到的是「看得见的那部分」。",
          "只拍到顶面时量到的是顶面的包围盒，不是物体的真实尺寸；点云缺失（遮挡、阴影）会让某一维偏小。",
          "PCA 有向外接盒，长 ≥ 宽 ≥ 高；尺寸是沿主轴的极差（mm）" },

        { Method::Section, "section", "截面轮廓", 1, "被测区域", nullptr,
          "在 ROI 上沿主方向取一条剖面，画出高度随距离变化的轮廓（显示在「截面轮廓」页）。",
          "ROI 框住要看的区域：长边方向就是剖面方向。",
          "轮廓点（距离 mm，高度 mm）；采样步长 = 相邻采样点的间隔（mm）。",
          "看点数与步长：步长明显大于数据点距时曲线被平滑，细节会丢。",
          "ROI 的长宽比决定剖面方向（正方形时由点分布的主轴决定）；框到两个高度面时曲线出现台阶，属正常。",
          "轮廓 = 每个距离分箱内点高度的中位数（mm）" },

        { Method::Repeatability, "repeatability", "重复性", 0, nullptr, nullptr,
          "对同一个尺寸反复测量，看它本身的波动（σ、极差），判断测量系统稳不稳。",
          "本方法不需要 ROI：先用别的方法测一次并点「加入重复性」，重新拍照、重新框选后再测一次，"
          "攒够样本。",
          "n = 样本数；均值（mm）；σ = 标准差（mm）；极差 = 最大 − 最小（mm）；±3σ（mm）。",
          "n 至少 5 个才有意义；σ 是「重复测同一个东西的波动」，不是零件公差。",
          "把不同零件、不同位置的测量值混进同一个序列，σ 会变成「零件之间的差异」，不能当重复性。",
          "σ 为样本标准差（n−1）；极差 = 最大 − 最小（mm）" },
    };
    count = static_cast<int>(sizeof(table) / sizeof(table[0]));
    return table;
}

inline const MethodSpec& methodSpec(Method m)
{
    int n = 0;
    const MethodSpec* table = methodSpecs(n);
    for (int i = 0; i < n; ++i)
        if (table[i].method == m)
            return table[i];
    return table[0];   // 只在 Method::Count 等非法值上发生
}

// "本方法只需 ROI A（被测面）" / "本方法需要 ROI A + ROI B（基准面 / 被测面）"
// / "本方法不需要 ROI" —— 页面按它提示，拖框时按它限制（P3.2）。
inline std::string roiRequirementText(Method m)
{
    const MethodSpec& s = methodSpec(m);
    if (s.roiCount <= 0)
        return "本方法不需要 ROI（用重复性序列）";
    if (s.roiCount == 1)
        return std::string("本方法只需 ROI A（") + (s.roiA ? s.roiA : "") + "）";
    return std::string("本方法需要 ROI A + ROI B（") + (s.roiA ? s.roiA : "") + " / "
           + (s.roiB ? s.roiB : "") + "）";
}

// ── ROI 拖框策略（纯逻辑，可单测）─────────────────────────────────────
//
// 用户第 2 条的原话是"目前支持两个 ROI A/B，有些方法只用一个或多个，你看是否
// 需要单独做个限制"。上一版的做法是第 3 次拖框**悄悄清空重来**——用户不知道
// 刚才那两个框没了。这里把策略变成数据：新框该落到哪个槽、要不要先清空、以及
// 该对用户说什么。
struct RoiDragPlan {
    int slot = -1;          // 新框落到哪个 ROI 槽；-1 = 本方法不用 ROI，忽略这次拖框
    bool clearAll = false;  // true = 先清掉已有的框（并且必须提示，不能悄悄清）
    std::string note;       // 给用户看的一句话（页面的 ROI 提示行）
};

inline RoiDragPlan planRoiDrag(int roiCount, int haveRects)
{
    RoiDragPlan p;
    if (roiCount <= 0) {
        p.note = "本方法不需要 ROI：这次拖框已忽略（需要清掉已有的框请点「清除 ROI」）";
        return p;
    }
    if (roiCount == 1) {
        // 单 ROI 方法：再拖一次就是"重画 A"，不是"从头再来"。
        p.slot = 0;
        p.note = haveRects >= 1 ? "本方法只需 ROI A：已用新的框替换 ROI A"
                                : "本方法只需 ROI A：在 2D 视图上拖框即选中";
        return p;
    }
    if (haveRects < roiCount) {
        p.slot = haveRects;
        p.note = haveRects == 0
            ? "本方法需要 ROI A + ROI B：当前 0/2，请先框 ROI A"
            : "本方法需要 ROI A + ROI B：当前 1/2，再拖一次框 ROI B";
        return p;
    }
    // 已经画满：明确告诉用户"从 A 重新开始"，而不是默默清空。
    p.slot = 0;
    p.clearAll = true;
    p.note = "本方法需要 ROI A + ROI B：已选满 2/2，这次拖框已从 ROI A 重新开始"
             "（原来的 A、B 已清除）";
    return p;
}

// 按方法本身给出提示语，需要角色名时拼上 spec 里的名字。
inline std::string roiDragNote(Method m, int haveRects)
{
    RoiDragPlan p = planRoiDrag(methodSpec(m).roiCount, haveRects);
    const MethodSpec& s = methodSpec(m);
    if (s.roiCount == 2 && p.slot == 0 && !p.clearAll && haveRects == 0)
        return std::string(p.note) + "（" + (s.roiA ? s.roiA : "") + "）";
    if (s.roiCount == 2 && p.slot == 1)
        return std::string(p.note) + "（" + (s.roiB ? s.roiB : "") + "）";
    return p.note;
}

// 当前选择状态的一句话（没有新拖框时要显示的那句，与 planRoiDrag 的"动作"
// 提示区分开：动作提示说的是"刚才那次拖框干了什么"，状态说的是"现在到哪一步了"）。
inline std::string roiStateText(int roiCount, int haveRects)
{
    if (roiCount <= 0)
        return "本方法不需要 ROI：用别的方法测量后点「加入重复性」累积样本";
    if (roiCount == 1)
        return haveRects >= 1 ? "ROI A 已选好，可以点「测量」"
                              : "未选择 — 在 2D 视图上按住左键拖框（只需 ROI A）";
    if (haveRects <= 0)
        return "未选择 — 在 2D 视图上按住左键拖框，依次为 ROI A、ROI B";
    if (haveRects == 1)
        return "已选 1/2：再拖一次框 ROI B";
    return "ROI A + ROI B 已就绪，可以点「测量」";
}

// 拖框**落定之后**「测量区域」那一行该显示哪一句（W1 修正）。
//
// 缺陷现象：双 ROI 方法（高度段差 / 面面距离夹角）拖完第 2 个框，上面的
// "ROI A: …；ROI B: …" 已经列出两个框，下面却还在说"当前 1/2，再拖一次框
// ROI B"——因为面板把 planRoiDrag() 的**动作提示**当成了状态句用，而那句话是
// 按"拖框之前"的框数写的（第 1 个框落下后还会说"当前 0/2"）。
//
// 规则：落定之后讲**现在的状态**（roiStateText(roiCount, haveRectsAfter)），
// 只有两类例外必须保留动作说明——
//   1) 这次拖框把已有的框清掉了（第 3 次拖框，clearAll）：得解释框为什么没了；
//   2) 这次拖框被忽略（slot < 0，本方法不用 ROI）：得解释为什么没生效。
// 这两类正是用户实测"提示是对的"的那两条，所以原样透传 plan.note。
inline std::string roiNoteAfterDrag(int roiCount, const RoiDragPlan& plan, int haveRectsAfter)
{
    if (plan.slot < 0 || plan.clearAll)
        return plan.note;
    return roiStateText(roiCount, haveRectsAfter);
}

// ── P4 的日志正文（纯文本，界面侧加 [测量-说明] / [测量-结果] 前缀）────

// 操作日志的两条前缀。放在这里而不是只写在界面里，是因为"选中方法时写说明、
// 测完写结果"是用户直接读到的契约：两条前缀必须不同，且都要带方括号。
inline const char* kExplainLogTag = "测量-说明";
inline const char* kResultLogTag = "测量-结果";

inline std::string logTagged(const char* tag, const std::string& text)
{
    return std::string("[") + tag + "] " + text;
}

inline std::string methodExplainLine(Method m)
{
    const MethodSpec& s = methodSpec(m);
    std::string out = s.name;
    out += " —— 用途：";
    out += s.purpose;
    out += "；ROI 怎么画：";
    out += s.howTo;
    if (s.roiCount > 0) {
        out += "；";
        out += roiRequirementText(m);
    }
    out += "；输出：";
    out += s.outputs;
    out += "；可信度：";
    out += s.confidence;
    out += "；常见错法：";
    out += s.pitfalls;
    return out;
}

// 一行结果项（值已格式化好）："最小区域 PV = 0.0312 mm"。
struct ResultItem {
    std::string label;
    std::string value;
    std::string unit;
};

// "[测量-结果]" 的正文：方法名、关键数值、可信度、以及本次用的口径。
inline std::string resultLine(Method m, const std::vector<ResultItem>& items,
                              const std::string& confidenceLabel)
{
    const MethodSpec& s = methodSpec(m);
    std::string out = s.name;
    out += "：";
    for (std::size_t i = 0; i < items.size(); ++i) {
        if (i)
            out += "；";
        out += items[i].label;
        out += " = ";
        out += items[i].value;
        if (!items[i].unit.empty()) {
            out += " ";
            out += items[i].unit;
        }
    }
    if (!confidenceLabel.empty()) {
        out += "（";
        out += confidenceLabel;
        out += "）";
    }
    out += "；口径：";
    out += s.convention;
    return out;
}

// 方法跑不起来时（点数不够、ROI 没画全…）的日志正文。
inline std::string resultRefusalLine(Method m, const std::string& reason)
{
    return std::string(methodSpec(m).name) + "：未完成 —— " + reason;
}

} // namespace MeasureTools
