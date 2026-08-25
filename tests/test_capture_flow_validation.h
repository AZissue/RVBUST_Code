#pragma once

#include <QObject>

class TestCaptureFlowValidation : public QObject {
    Q_OBJECT
private slots:
    void acceptsCleanValues();
    void rejectsNanInfVariants();
    void validatesRequiredFieldsByMode();
    void rejectsNonNumericValues();
    void rejectsNanInfViaSaveValidation();
    void acceptsValidInputs();
    void caliboardQualityGates();
    void caliboardQualityThresholdConfigurable();
    void detectsCjkFormatChars();
    void acceptsEnglishCommaSeparatedValues();
    void rejectsChineseFormatOnSave();
};
