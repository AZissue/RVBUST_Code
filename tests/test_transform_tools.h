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
    // 格式目录（24 种欧拉约定 / 四元数 / 矩阵 / 轴角）已移到
    // tests/test_robot_data_formats.cpp；这里只测与格式无关的几何原语。
    void eulerRpyKnownAngles();
    void eulerRpyDegreeMatchesRadian();
    void toMillimetersConversion();
    void quatToRotNormalized();
    void quatMatchesRotationVector();
    void rotationOrthonormal();
    void eyeToHandPoint();
    void eyeInHandPoint();
    void walkPointDispatch();
    void rotationVectorZeroIsIdentity();
};
