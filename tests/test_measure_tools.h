#pragma once

#include <QObject>

// Synthetic-data tests for the measurement kernel (src/logic/MeasureTools.h).
// Every expected number is either constructed exactly (a 3.000 mm step, an
// 89.613° tilt, a 100x60x20 box) or hand-computed, and the tolerances are the
// ones the task fixed — they are not relaxed to make a failure disappear.
class TestMeasureTools : public QObject
{
    Q_OBJECT

private slots:
    void flatnessPvRmsAndMinimumZone();
    void flatnessRejectsFlyers();
    void deviationIsPositiveTowardsCamera();
    void heightStepIsThreeMillimetres();
    void heightIsSigned();
    void planeAngleMatchesConstructedTilt();
    void parallelPlaneDistance();
    void nonParallelPairHasNoDistance();
    void circleDiameterWithinTolerance();
    void circleRejectsOutliers();
    void boundingBoxExtents();
    void boundingBoxIsOriented();
    void repeatabilityHandComputed();
    void robustLimitsResistFlyer();
    void roiExtractionSkipsNan();
    void sectionProfileFollowsStep();
    void colormapMatchesReferenceFormula();
    void cloudColorsAlignWithFilteredCloud();
    void cloudColorsHighlightOnlyTheRoi();
};
