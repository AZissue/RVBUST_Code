// Throwaway end-to-end probe: run the *app's own* CalibrationService over the
// synthetic axis-angle hand-eye set, so the "correct format -> totalMeanError 0"
// claim is about our code and not about a numpy re-implementation of it.
//
//   e2e_main <dir> <rpy|rotvec> <deg|rad>
//
// <dir> must contain camera.txt / tcp.txt (3 numbers per line) and
// card_pose.txt (the card format: "x y z rx ry rz", spaces).
#include <cstdio>
#include <string>
#include <vector>

#include <QFile>
#include <QTextStream>
#include <QString>

#include "logic/CalibrationService.h"
#include "models/CalibrationMode.h"

static std::vector<QString> readLines(const QString& path)
{
    std::vector<QString> out;
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
        return out;
    QTextStream ts(&f);
    while (!ts.atEnd()) {
        const QString line = ts.readLine().trimmed();
        if (!line.isEmpty())
            out.push_back(line);
    }
    return out;
}

int main(int argc, char** argv)
{
    if (argc < 4) {
        std::printf("usage: e2e_main <dir> <rpy|rotvec> <deg|rad>\n");
        return 2;
    }
    const QString dir = QString::fromLocal8Bit(argv[1]);
    const std::string fmtArg = argv[2];
    const std::string unitArg = argv[3];

    const auto camera = readLines(dir + QStringLiteral("/camera.txt"));
    const auto tcp = readLines(dir + QStringLiteral("/tcp.txt"));
    const auto pose = readLines(dir + QStringLiteral("/card_pose.txt"));
    if (camera.empty() || tcp.empty() || pose.empty()) {
        std::printf("missing input files in %s\n", qPrintable(dir));
        return 2;
    }

    CalibrationService::Params p;
    p.calibType = CalibType::TcpTouch;
    p.eyeInHand = true;
    p.poseFormat = (fmtArg == "rotvec")
        ? TransformTools::RotationFormat::RotationVector
        : TransformTools::RotationFormat::EulerRpy;
    p.poseAngleUnit = (unitArg == "rad")
        ? TransformTools::AngleUnit::Radian
        : TransformTools::AngleUnit::Degree;

    int poseType = -99;
    const QString firstLine = CalibrationService::toSdkPoseLine(
        pose.front(), p.poseFormat, p.poseAngleUnit, poseType);
    std::printf("format=%s unit=%s -> poseType=%d\n", fmtArg.c_str(),
                unitArg.c_str(), poseType);
    std::printf("first card line : %s\n", qPrintable(pose.front()));
    std::printf("first SDK  line : %s\n", qPrintable(firstLine));

    const CalibrationService::Result r =
        CalibrationService::calibrate(QString(), camera, pose, tcp, p);
    std::printf("ok=%d retCode=%d error=%s\n", r.ok ? 1 : 0, r.retCode,
                qPrintable(r.error));
    if (!r.ok)
        return 1;

    std::printf("totalMeanError=%.6f  usedCount=%d\n", r.totalMeanError, r.usedCount);
    for (int row = 0; row < 4; ++row) {
        std::printf("  %14.6f %14.6f %14.6f %14.6f\n",
                    r.matrix[row * 4 + 0], r.matrix[row * 4 + 1],
                    r.matrix[row * 4 + 2], r.matrix[row * 4 + 3]);
    }
    std::fflush(stdout);
    return 0;
}
