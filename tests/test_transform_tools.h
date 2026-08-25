#pragma once

#include <QObject>

class TestTransformTools : public QObject {
    Q_OBJECT
private slots:
    void mul4Identity();
    void mul4TranslationComposition();
    void transformPointPureTranslation();
    void makeMat4Assembly();
    void toRadians();
    void eulerRpyKnownAngles();
    void eulerWprKnownAngles();
    void eulerRpyDegreeMatchesRadian();
    void toMillimetersConversion();
    void quatToRotNormalized();
    void quatMatchesRotationVector();
    void rotationOrthonormal();
    void rotationFromValuesQuaternionOrders();
    void rotationFromValuesMatrixPassthrough();
    void rotationFromValuesRejectsWrongCount();
    void rotationValueCounts();
    void poseToMat4TranslationAndRotation();
    void eyeToHandPoint();
    void eyeInHandPoint();
    void walkPointDispatch();
    void rotationVectorZeroIsIdentity();
};
