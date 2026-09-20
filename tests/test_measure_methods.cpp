#include "test_measure_methods.h"

#include <QtTest>

#include <set>
#include <string>
#include <vector>

#include "logic/MeasureMethods.h"

using namespace MeasureTools;

namespace {

// 用户在第 7 回合 P3.2 里给的声明样式：{1, "被测面"} / {2, "基准面", "被测面"}。
// 这里把 8 个方法逐个钉死，任何"少要一个 ROI"的改动都会立刻红。
struct Expected {
    Method method;
    int roiCount;
    const char* roiA;
    const char* roiB;
};

const Expected kExpected[] = {
    { Method::Flatness,      1, "被测面", nullptr },
    { Method::StepHeight,    2, "基准面", "被测面" },
    { Method::PlanePair,     2, "面 A", "面 B" },
    { Method::RingCircle,    1, "环形材料", nullptr },
    { Method::HoleDiameter,  1, "孔 + 约 2 个点距的材料", nullptr },
    { Method::BoundingBox,   1, "整个物体", nullptr },
    { Method::Section,       1, "被测区域", nullptr },
    { Method::Repeatability, 0, nullptr, nullptr },
};

bool contains(const std::string& hay, const char* needle)
{
    return hay.find(needle) != std::string::npos;
}

bool contains(const std::string& hay, const std::string& needle)
{
    return hay.find(needle) != std::string::npos;
}

QString q(const std::string& s)
{
    return QString::fromUtf8(s.c_str());
}

} // namespace

void TestMeasureMethods::catalogueCoversEveryMethodOnce()
{
    int n = 0;
    const MethodSpec* specs = methodSpecs(n);
    QCOMPARE(n, static_cast<int>(sizeof(kExpected) / sizeof(kExpected[0])));
    QCOMPARE(static_cast<int>(Method::Count), n);

    std::set<std::string> ids;
    std::set<std::string> names;
    for (int i = 0; i < n; ++i) {
        const MethodSpec& s = specs[i];
        // 每一项都必须能填出一个"这一页是什么"的最小集合。
        QVERIFY(s.id && *s.id);
        QVERIFY(s.name && *s.name);
        QVERIFY(s.purpose && *s.purpose);
        QVERIFY(s.howTo && *s.howTo);
        QVERIFY(s.outputs && *s.outputs);
        QVERIFY(s.confidence && *s.confidence);
        QVERIFY(s.pitfalls && *s.pitfalls);
        QVERIFY(s.convention && *s.convention);
        // id / 名字不能重（左侧列表项与日志都靠它们区分）。
        QVERIFY(ids.insert(s.id).second);
        QVERIFY(names.insert(s.name).second);
        // 目录顺序必须与枚举顺序一致：左侧列表的顺序就是用户看到的顺序。
        QCOMPARE(static_cast<int>(s.method), i);
        // 目录里的 id 必须与内核的稳定 id 一致（日志、测试数据、manifest 共用）。
        QCOMPARE(q(s.id), q(methodId(s.method)));
    }
}

void TestMeasureMethods::roiCountMatchesTheKernel()
{
    for (const Expected& e : kExpected) {
        const MethodSpec& s = methodSpec(e.method);
        // 目录与内核两张表必须说同一件事：界面提示几个 ROI，算法就必须要几个。
        QCOMPARE(s.roiCount, roiCountFor(e.method));
        QCOMPARE(s.roiCount, e.roiCount);
        QCOMPARE(methodSpec(e.method).method, e.method);
    }
}

void TestMeasureMethods::roiRolesMatchTheDeclaredRequirement()
{
    for (const Expected& e : kExpected) {
        const MethodSpec& s = methodSpec(e.method);
        if (e.roiA) {
            QVERIFY(s.roiA);
            QCOMPARE(q(s.roiA), q(e.roiA));
        } else {
            QVERIFY(!s.roiA);
        }
        if (e.roiB) {
            QVERIFY(s.roiB);
            QCOMPARE(q(s.roiB), q(e.roiB));
        } else {
            // 只需要一个 ROI 的方法不得声明第二个：多要一个框就是白让用户
            // 多拖一次，少要一个框则会让算法拿到半个输入。
            QVERIFY(!s.roiB);
        }
    }
}

void TestMeasureMethods::roiRequirementTextIsExplicit()
{
    for (const Expected& e : kExpected) {
        const std::string text = roiRequirementText(e.method);
        QVERIFY(!text.empty());
        if (e.roiCount == 0) {
            QVERIFY(contains(text, "不需要 ROI"));
            continue;
        }
        if (e.roiCount == 1) {
            QVERIFY(contains(text, "只需 ROI A"));
            QVERIFY(!contains(text, "ROI B"));
            QVERIFY(contains(text, e.roiA));
        } else {
            QVERIFY(contains(text, "ROI A + ROI B"));
            QVERIFY(contains(text, e.roiA));
            QVERIFY(contains(text, e.roiB));
        }
    }
}

void TestMeasureMethods::thirdDragTellsTheUserInsteadOfSilentRestart()
{
    // 两个 ROI 的方法：第一次落 A、第二次落 B。
    {
        const RoiDragPlan first = planRoiDrag(2, 0);
        QCOMPARE(first.slot, 0);
        QVERIFY(!first.clearAll);
        QVERIFY(contains(first.note, "ROI A"));
        const RoiDragPlan second = planRoiDrag(2, 1);
        QCOMPARE(second.slot, 1);
        QVERIFY(!second.clearAll);
        QVERIFY(contains(second.note, "ROI B"));
    }
    // 第三次：**必须**告诉用户"已从 A 重新开始、原来的框清掉了"。
    // 这正是用户抱怨的"默不作声地重新开始"。
    const RoiDragPlan third = planRoiDrag(2, 2);
    QCOMPARE(third.slot, 0);
    QVERIFY(third.clearAll);
    QVERIFY(contains(third.note, "重新开始"));
    QVERIFY(contains(third.note, "ROI A"));
    QVERIFY(contains(third.note, "ROI B"));
    QVERIFY(contains(third.note, "已清除"));
    // 再拖（第 4、5 次…）行为不变：每次都从 A 开始，且每次都说明。
    const RoiDragPlan fourth = planRoiDrag(2, 3);
    QCOMPARE(fourth.slot, 0);
    QVERIFY(fourth.clearAll);
    // 落点提示必须带上方法自己的角色名，用户才知道"这一框该框哪儿"。
    const std::string note = roiDragNote(Method::StepHeight, 1);
    QVERIFY(contains(note, "被测面"));
}

void TestMeasureMethods::singleRoiMethodReplacesInsteadOfRestarting()
{
    // 单 ROI 方法：再拖一次是"重画 A"，绝不清空（没有什么可清的）。
    const RoiDragPlan p1 = planRoiDrag(1, 0);
    QCOMPARE(p1.slot, 0);
    QVERIFY(!p1.clearAll);
    QVERIFY(contains(p1.note, "只需 ROI A"));

    const RoiDragPlan p2 = planRoiDrag(1, 1);
    QCOMPARE(p2.slot, 0);
    QVERIFY(!p2.clearAll);
    QVERIFY(contains(p2.note, "替换"));

    // 即使框已经多到两个（比如从上一个方法留下来的），单 ROI 方法也只认 A。
    const RoiDragPlan p3 = planRoiDrag(1, 2);
    QCOMPARE(p3.slot, 0);
    QVERIFY(!p3.clearAll);
}

void TestMeasureMethods::dragIsIgnoredByMethodsWithoutRoi()
{
    // 重复性统计不需要 ROI：拖框不该改变它，也不该悄悄吞掉。
    for (int have = 0; have <= 2; ++have) {
        const RoiDragPlan p = planRoiDrag(0, have);
        QCOMPARE(p.slot, -1);
        QVERIFY(!p.clearAll);
        QVERIFY(!p.note.empty());
        // 已有的框怎么清掉，得说清楚（视窗工具栏的「清除 ROI」）。
        QVERIFY(contains(p.note, "清除 ROI"));
    }
}

void TestMeasureMethods::roiStateTextDescribesProgress()
{
    // 状态提示与"这次拖框干了什么"是两句话，但都必须说清到哪一步了。
    const std::string none2 = roiStateText(2, 0);
    const std::string half2 = roiStateText(2, 1);
    const std::string full2 = roiStateText(2, 2);
    QVERIFY(contains(none2, "ROI A"));
    QVERIFY(contains(half2, "1/2"));
    QVERIFY(contains(half2, "ROI B"));
    QVERIFY(contains(full2, "2/2") || contains(full2, "已就绪"));
    QVERIFY(none2 != half2);
    QVERIFY(half2 != full2);

    QVERIFY(contains(roiStateText(1, 0), "只需 ROI A"));
    QVERIFY(contains(roiStateText(1, 1), "ROI A"));
    QVERIFY(contains(roiStateText(0, 0), "不需要 ROI"));
}

void TestMeasureMethods::explainLineCarriesEverySection()
{
    // P4：[测量-说明] 必须把"怎么用"讲全，缺一段就等于用户还得回头问。
    for (const Expected& e : kExpected) {
        const MethodSpec& s = methodSpec(e.method);
        const std::string line = methodExplainLine(e.method);
        QVERIFY(contains(line, s.name));
        QVERIFY(contains(line, "用途"));
        QVERIFY(contains(line, s.purpose));
        QVERIFY(contains(line, "ROI"));
        QVERIFY(contains(line, s.howTo));
        QVERIFY(contains(line, "输出"));
        QVERIFY(contains(line, s.outputs));
        QVERIFY(contains(line, "可信度"));
        QVERIFY(contains(line, s.confidence));
        QVERIFY(contains(line, "常见错法"));
        QVERIFY(contains(line, s.pitfalls));
        if (e.roiCount > 0)
            QVERIFY(contains(line, roiRequirementText(e.method)));
    }
}

void TestMeasureMethods::everyMethodStatesWhatTheNumbersMean()
{
    // 第 11 回合任务 005：说明搬到操作日志，所以**每个方法**的
    // [测量-说明] 都要有四个小标题（用途/怎么用/输出/怎么看结果），
    // [测量-结果] 都要在数值之后补一句"这组数说明：…"，且该句不能是空的。
    const std::vector<ResultItem> items = { { "数值", "1.000", "mm" } };
    for (const Expected& e : kExpected) {
        const std::string explain = methodExplainLine(e.method);
        QVERIFY2(contains(explain, "用途："), explain.c_str());
        QVERIFY2(contains(explain, "怎么用："), explain.c_str());
        QVERIFY2(contains(explain, "输出："), explain.c_str());
        QVERIFY2(contains(explain, "怎么看结果："), explain.c_str());

        const std::string result = resultLine(e.method, items, "");
        QVERIFY2(contains(result, "这组数说明："), result.c_str());
        const std::size_t at = result.find("这组数说明：");
        QVERIFY2(result.size() > at + std::string("这组数说明：").size(),
                 "「这组数说明：」后面必须真的跟一句话");
        // 数值本身一个字符都不许变（老断言靠的就是这个格式）。
        QVERIFY2(contains(result, "数值 = 1.000 mm"), result.c_str());
    }
}

void TestMeasureMethods::resultLineCarriesValuesAndConvention()
{
    const std::vector<ResultItem> items = {
        { "孔直径", "5.0123", "mm" },
        { "孔半径", "2.5062", "mm" },
        { "扇区覆盖", "34/36", "" },
    };
    const std::string line = resultLine(Method::HoleDiameter, items,
                                        "36 点，高；扇区覆盖 34/36");
    QVERIFY(contains(line, methodSpec(Method::HoleDiameter).name));
    QVERIFY(contains(line, "孔直径 = 5.0123 mm"));
    QVERIFY(contains(line, "孔半径 = 2.5062 mm"));
    // 没有单位的项不能留下一个孤零零的空格。
    QVERIFY(contains(line, "扇区覆盖 = 34/36"));
    QVERIFY(!contains(line, "34/36 "));
    QVERIFY(contains(line, "扇区覆盖 34/36"));
    // 口径必须写进日志：用户要对数就要知道这个数是怎么来的。
    QVERIFY(contains(line, "口径"));
    QVERIFY(contains(line, methodSpec(Method::HoleDiameter).convention));

    // 空结果也要能成句（不该出现"方法名："后面什么都没有还带个分号）。
    const std::string bare = resultLine(Method::Flatness, {}, "");
    QVERIFY(contains(bare, methodSpec(Method::Flatness).name));
    QVERIFY(contains(bare, "口径"));
}

void TestMeasureMethods::refusalLineNamesTheMethod()
{
    const std::string line = resultRefusalLine(Method::BoundingBox, "ROI A 内点数不足");
    QVERIFY(contains(line, methodSpec(Method::BoundingBox).name));
    QVERIFY(contains(line, "未完成"));
    QVERIFY(contains(line, "ROI A 内点数不足"));
}

void TestMeasureMethods::logTagsSeparateExplainFromResult()
{
    // P4 的日志契约：选中方法写 [测量-说明]，测完写 [测量-结果]。两条前缀必须
    // 不同（否则日志里分不出"这个方法怎么用"和"我刚测出来的数"），都必须带
    // 方括号，且正文里不能再混进前缀以外的方括号前缀。
    const std::string explainTag = kExplainLogTag;
    const std::string resultTag = kResultLogTag;
    QVERIFY(explainTag != resultTag);
    QVERIFY(contains(explainTag, "测量"));
    QVERIFY(contains(resultTag, "测量"));
    QVERIFY(contains(resultTag, "结果"));

    const std::string explain =
        logTagged(kExplainLogTag, methodExplainLine(Method::HoleDiameter));
    const std::string result =
        logTagged(kResultLogTag, resultLine(Method::HoleDiameter, {}, "36 点，高"));
    const std::string refusal =
        logTagged(kResultLogTag, resultRefusalLine(Method::HoleDiameter, "点数不足"));

    QVERIFY(explain.rfind("[测量-说明] ", 0) == 0);
    QVERIFY(result.rfind("[测量-结果] ", 0) == 0);
    // 拒绝也必须走"结果"这条前缀：用户点了「测量」，日志里就该有一次回应。
    QVERIFY(refusal.rfind("[测量-结果] ", 0) == 0);
    QVERIFY(explain.rfind("[测量-结果] ", 0) != 0);
    QVERIFY(result.rfind("[测量-说明] ", 0) != 0);
    // 前缀后面必须紧跟正文，不能只有一个空格。
    QVERIFY(explain.size() > std::string("[测量-说明] ").size());
    QVERIFY(result.size() > std::string("[测量-结果] ").size());
}

// W1（第 10 回合）：拖框**落定之后**「测量区域」那一行该是哪句。
// 缺陷现象：双 ROI 方法拖完第 2 个框，上面已经列出 "ROI A: …；ROI B: …"，
// 下面却还在说"当前 1/2，再拖一次框 ROI B"——用户以为 ROI B 没画上。
// 修法：落定之后讲现在的状态；只有"清空重来"和"这次拖框被忽略"两类
// （用户实测"提示是对的"的那两条）保留动作说明。
void TestMeasureMethods::noteAfterDragMatchesTheState()
{
    // 第 2 个框落下：显示的那句必须**就是**"就绪"句。
    const RoiDragPlan second = planRoiDrag(2, 1);
    QCOMPARE(second.slot, 1);
    QVERIFY(!second.clearAll);
    const std::string afterSecond = roiNoteAfterDrag(2, second, 2);
    QCOMPARE(q(afterSecond), q(roiStateText(2, 2)));
    QVERIFY(contains(afterSecond, "已就绪"));
    QVERIFY(!contains(afterSecond, "1/2"));
    QVERIFY(!contains(afterSecond, "再拖一次"));

    // 第 1 个框落下后也不能停在"当前 0/2"（动作提示是按拖框前的框数写的）。
    const std::string afterFirst = roiNoteAfterDrag(2, planRoiDrag(2, 0), 1);
    QCOMPARE(q(afterFirst), q(roiStateText(2, 1)));
    QVERIFY(!contains(afterFirst, "0/2"));

    // 第 3 次拖框（已选满 → 清空重来）是动作提示：原样保留。
    const RoiDragPlan third = planRoiDrag(2, 2);
    QVERIFY(third.clearAll);
    QCOMPARE(q(roiNoteAfterDrag(2, third, 1)), q(third.note));
    QVERIFY(contains(roiNoteAfterDrag(2, third, 1), "重新开始"));

    // 本方法不用 ROI：这次拖框被忽略，同样保留动作说明。
    const RoiDragPlan ignored = planRoiDrag(0, 0);
    QVERIFY(ignored.slot < 0);
    QCOMPARE(q(roiNoteAfterDrag(0, ignored, 0)), q(ignored.note));

    // 单 ROI 方法：替换之后显示的也是"现在的状态"。
    QCOMPARE(q(roiNoteAfterDrag(1, planRoiDrag(1, 1), 1)), q(roiStateText(1, 1)));
}
