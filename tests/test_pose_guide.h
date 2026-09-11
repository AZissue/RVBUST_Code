#pragma once

#include <QObject>

class TestPoseGuide : public QObject {
    Q_OBJECT
private slots:
    void translationBasic();
    void rotationIdentity();
    void rotation90Z();
    void rotationSymmetric();
    void guideEmpty();
    void guideTooClose();
    void guideFarPosition();
    void guideFarAngle();
    void guideBoundary();
};
