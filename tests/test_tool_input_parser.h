#pragma once

#include <QObject>

class TestToolInputParser : public QObject {
    Q_OBJECT
private slots:
    void parsesSpaceSeparated16();
    void parsesCommaSeparated16();
    void parsesMixedSeparators();
    void parsesScientificNotation();
    void trimsSurroundingWhitespace();
    void rejectsWrongCount();
    void rejectsEmptyInput();
    void rejectsChineseComma();
    void rejectsFullWidthDigits();
    void rejectsNonNumericToken();
    void reportsBadToken();
};
