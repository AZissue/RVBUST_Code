#pragma once

#include <QObject>

class TestDataQualityCheck : public QObject {
    Q_OBJECT
private slots:
    void parsePoseText();
    void countEmpty();
    void countTooFew();
    void countAdvisory();
    void countEnough();
    void nearDuplicate();
    void noNearDuplicate();
    void outlierPosition();
    void frameErrorHigh();
    void spreadInsufficient();
    void overallOk();
};
