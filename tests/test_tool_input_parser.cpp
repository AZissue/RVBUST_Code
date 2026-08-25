#include "test_tool_input_parser.h"

#include "logic/ToolInputParser.h"

#include <QtTest>
#include <cmath>

using namespace ToolInputParser;

void TestToolInputParser::parsesSpaceSeparated16()
{
    const auto r = parseNumberList(
        "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1", 16);
    QCOMPARE(r.status, ParseStatus::Ok);
    QCOMPARE(r.values.size(), 16u);
    QCOMPARE(r.values[0], 1.0);
    QCOMPARE(r.values[5], 1.0);
    QCOMPARE(r.values[10], 1.0);
    QCOMPARE(r.values[15], 1.0);
    QCOMPARE(r.values[3], 0.0);
}

void TestToolInputParser::parsesCommaSeparated16()
{
    const auto r = parseNumberList(
        "1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1", 16);
    QCOMPARE(r.status, ParseStatus::Ok);
    QCOMPARE(r.values.size(), 16u);
    QCOMPARE(r.values[5], 1.0);
}

void TestToolInputParser::parsesMixedSeparators()
{
    const auto r = parseNumberList("1, 2  3,\t4", 4);
    QCOMPARE(r.status, ParseStatus::Ok);
    QCOMPARE(r.values.size(), 4u);
    QCOMPARE(r.values[0], 1.0);
    QCOMPARE(r.values[3], 4.0);
}

void TestToolInputParser::parsesScientificNotation()
{
    const auto r = parseNumberList("1e-3, -2.5e2, 3.14", 3);
    QCOMPARE(r.status, ParseStatus::Ok);
    QVERIFY(std::abs(r.values[0] - 0.001) < 1e-12);
    QVERIFY(std::abs(r.values[1] + 250.0) < 1e-9);
    QVERIFY(std::abs(r.values[2] - 3.14) < 1e-9);
}

void TestToolInputParser::trimsSurroundingWhitespace()
{
    const auto r = parseNumberList("  1  2  3  ", 3);
    QCOMPARE(r.status, ParseStatus::Ok);
    QCOMPARE(r.values.size(), 3u);
}

void TestToolInputParser::rejectsWrongCount()
{
    const auto r = parseNumberList("1 2 3 4 5 6 7 8 9 10 11 12 13 14 15", 16);
    QCOMPARE(r.status, ParseStatus::WrongCount);
    QCOMPARE(r.tokenCount, 15u);
    QVERIFY(r.values.empty());
}

void TestToolInputParser::rejectsEmptyInput()
{
    const auto r = parseNumberList("   ", 3);
    QCOMPARE(r.status, ParseStatus::WrongCount);
    QCOMPARE(r.tokenCount, 0u);
}

void TestToolInputParser::rejectsChineseComma()
{
    const auto r = parseNumberList("1，2，3", 3);
    QCOMPARE(r.status, ParseStatus::NonAscii);
}

void TestToolInputParser::rejectsFullWidthDigits()
{
    const auto r = parseNumberList("１ 2 3", 3);
    QCOMPARE(r.status, ParseStatus::NonAscii);
}

void TestToolInputParser::rejectsNonNumericToken()
{
    const auto r = parseNumberList("1 abc 3", 3);
    QCOMPARE(r.status, ParseStatus::InvalidToken);
    QCOMPARE(QString::fromStdString(r.badToken), QStringLiteral("abc"));
}

void TestToolInputParser::reportsBadToken()
{
    const auto r = parseNumberList("1 2 x 4", 4);
    QCOMPARE(r.status, ParseStatus::InvalidToken);
    QCOMPARE(QString::fromStdString(r.badToken), QStringLiteral("x"));
}
