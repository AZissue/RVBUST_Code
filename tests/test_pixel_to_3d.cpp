#include "test_pixel_to_3d.h"

#include <QtTest>
#include <QDir>
#include <QFile>
#include <QTemporaryDir>

#include "logic/PixelTo3DTools.h"
#include "logic/PlyPointReader.h"

using namespace PixelTo3DTools;

void TestPixelTo3D::alignedLookupBasic()
{
    // 4x3 grid; point value = its flat index so each lookup is verifiable.
    const int w = 4, h = 3;
    std::vector<double> xyz(static_cast<std::size_t>(w) * h * 3);
    for (int i = 0; i < w * h; ++i) {
        xyz[i * 3 + 0] = i;
        xyz[i * 3 + 1] = 100 + i;
        xyz[i * 3 + 2] = 200 + i;
    }
    std::array<double, 3> out{};

    std::size_t idx = 0;
    QVERIFY(alignedIndex(0, 0, w, h, idx) && idx == 0);
    QVERIFY(alignedIndex(3, 2, w, h, idx) && idx == 11);
    QVERIFY(alignedIndex(4, 0, w, h, idx) == false);
    QVERIFY(alignedIndex(0, 3, w, h, idx) == false);

    QVERIFY(pointAt(xyz, 0, out) && out[0] == 0.0);
    QVERIFY(pointAt(xyz, 11, out) && out[1] == 111.0);
    QVERIFY(pointAt(xyz, 12, out) == false);
}

void TestPixelTo3D::alignedLookupOutOfBounds()
{
    const int w = 2, h = 2;
    std::vector<double> xyz(12, 1.0);
    std::array<double, 3> out{};
    std::vector<int> index(4, 0);
    QVERIFY(queryIndex(index, w, h, -1, 0, xyz, out) == false);
    QVERIFY(queryIndex(index, w, h, 0, -1, xyz, out) == false);
    QVERIFY(queryIndex(index, w, h, 2, 0, xyz, out) == false);
    QVERIFY(queryIndex(index, w, h, 0, 0, xyz, out));
}

void TestPixelTo3D::alignedLookupRejectsNaN()
{
    std::vector<double> xyz = { 1, 2, 3, std::nan(""), 0, 0 };
    std::array<double, 3> out{};
    QVERIFY(pointAt(xyz, 0, out));
    QVERIFY(pointAt(xyz, 1, out) == false);
}

void TestPixelTo3D::projectedIndexRoundTrip()
{
    const Intrinsics k{ 500.0, 500.0, 320.0, 240.0 };
    const int w = 640, h = 480;

    // Plane at z=1000mm, 7x7 grid of 100mm pitch.
    std::vector<double> xyz;
    for (int r = -3; r <= 3; ++r)
        for (int c = -3; c <= 3; ++c)
            xyz.insert(xyz.end(), { c * 100.0, r * 100.0, 1000.0 });

    std::vector<int> index;
    const int filled = buildProjectedIndex(xyz, nullptr, k, w, h, index);
    QCOMPARE(filled, 49);
    QCOMPARE(static_cast<int>(index.size()), w * h);

    for (int r = -3; r <= 3; ++r) {
        for (int c = -3; c <= 3; ++c) {
            const std::array<double, 3> p = { c * 100.0, r * 100.0, 1000.0 };
            double u = 0, v = 0;
            QVERIFY(projectPoint(p, nullptr, k, u, v));
            const int px = static_cast<int>(std::lround(u));
            const int py = static_cast<int>(std::lround(v));
            std::array<double, 3> out{};
            QVERIFY(queryIndex(index, w, h, px, py, xyz, out));
            QVERIFY(std::abs(out[0] - p[0]) < 1e-9);
            QVERIFY(std::abs(out[1] - p[1]) < 1e-9);
            QVERIFY(std::abs(out[2] - p[2]) < 1e-9);
        }
    }
}

void TestPixelTo3D::projectedIndexWithExtrinsics()
{
    const Intrinsics k{ 500.0, 500.0, 320.0, 240.0 };
    const int w = 640, h = 480;

    // Cloud in a "base" frame shifted by (+100, -50, 0); extrinsics map the
    // base frame into the camera frame.
    std::vector<double> xyz;
    for (int r = -2; r <= 2; ++r)
        for (int c = -2; c <= 2; ++c)
            xyz.insert(xyz.end(), { c * 100.0, r * 100.0, 1000.0 });

    const double ext[16] = {
        1, 0, 0, 100,
        0, 1, 0, -50,
        0, 0, 1, 0,
        0, 0, 0, 1
    };

    std::vector<int> index;
    const int filled = buildProjectedIndex(xyz, ext, k, w, h, index);
    QCOMPARE(filled, 25);

    // Query the pixel of a known base-frame point projected through ext.
    const std::array<double, 3> baseP = { 200.0, 100.0, 1000.0 };
    double u = 0, v = 0;
    QVERIFY(projectPoint(baseP, ext, k, u, v));
    std::array<double, 3> out{};
    QVERIFY(queryIndex(index, w, h, static_cast<int>(std::lround(u)),
                       static_cast<int>(std::lround(v)), xyz, out));
    QVERIFY(std::abs(out[0] - baseP[0]) < 1e-9);
    QVERIFY(std::abs(out[1] - baseP[1]) < 1e-9);
}

void TestPixelTo3D::correspondIndexRoundTrip()
{
    const int w = 320, h = 240;
    std::vector<double> cmap;
    std::vector<double> xyz;
    // 10 points, each mapped to a distinct pixel.
    for (int i = 0; i < 10; ++i) {
        const int px = 50 + i * 20;
        const int py = 100;
        cmap.insert(cmap.end(), { static_cast<double>(px), static_cast<double>(py) });
        xyz.insert(xyz.end(), { i * 10.0, i * 20.0, 300.0 });
    }

    std::vector<int> index;
    const int filled = buildCorrespondIndex(cmap, w, h, index);
    QCOMPARE(filled, 10);

    std::array<double, 3> out{};
    QVERIFY(queryIndex(index, w, h, 50, 100, xyz, out));
    QVERIFY(std::abs(out[0] - 0.0) < 1e-9);
    QVERIFY(queryIndex(index, w, h, 230, 100, xyz, out));
    QVERIFY(std::abs(out[1] - 180.0) < 1e-9);
    QVERIFY(queryIndex(index, w, h, 51, 100, xyz, out) == false);
}

void TestPixelTo3D::plyReaderAscii()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString path = dir.path() + QStringLiteral("/ascii.ply");
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly | QIODevice::Text));
    f.write("ply\nformat ascii 1.0\nelement vertex 3\n"
            "property float x\nproperty float y\nproperty float z\n"
            "property uchar r\nproperty uchar g\nproperty uchar b\n"
            "element face 1\nproperty list uchar int vertex_indices\nend_header\n"
            "1.0 2.0 3.0 255 0 0\n4.0 5.0 6.0 0 255 0\n7.0 8.0 9.0 0 0 255\n"
            "3 0 1 2\n");
    f.close();

    const auto r = PlyPointReader::read(path.toStdString());
    QVERIFY2(r.ok, r.error.c_str());
    QCOMPARE(r.xyz.size(), static_cast<std::size_t>(9));
    QCOMPARE(r.xyz[0], 1.0);
    QCOMPARE(r.xyz[5], 6.0);
    QCOMPARE(r.xyz[8], 9.0);
}

void TestPixelTo3D::plyReaderBinaryFloat()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString path = dir.path() + QStringLiteral("/binary.ply");
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly));
    f.write("ply\nformat binary_little_endian 1.0\n"
            "comment Created by Rvbust Inc. length unit = millimeter\n"
            "element vertex 2\nproperty float x\nproperty float y\nproperty float z\n"
            "end_header\n");
    const float pts[6] = { 1.5f, 2.5f, 3.5f, -4.0f, 5.0f, 6.0f };
    f.write(reinterpret_cast<const char*>(pts), sizeof(pts));
    f.close();

    const auto r = PlyPointReader::read(path.toStdString());
    QVERIFY2(r.ok, r.error.c_str());
    QCOMPARE(r.xyz.size(), static_cast<std::size_t>(6));
    QCOMPARE(r.xyz[0], 1.5);
    QCOMPARE(r.xyz[2], 3.5);
    QCOMPARE(r.xyz[3], -4.0);
}

void TestPixelTo3D::plyReaderBadInputs()
{
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    QVERIFY(PlyPointReader::read((dir.path() + QStringLiteral("/missing.ply")).toStdString()).ok == false);

    const QString bad = dir.path() + QStringLiteral("/bad.ply");
    QFile f(bad);
    QVERIFY(f.open(QIODevice::WriteOnly | QIODevice::Text));
    f.write("not ply\n");
    f.close();
    QVERIFY(PlyPointReader::read(bad.toStdString()).ok == false);

    const QString noXyz = dir.path() + QStringLiteral("/noxyz.ply");
    QFile g(noXyz);
    QVERIFY(g.open(QIODevice::WriteOnly | QIODevice::Text));
    g.write("ply\nformat ascii 1.0\nelement vertex 1\nproperty float a\nend_header\n0 0 0\n");
    g.close();
    const auto r = PlyPointReader::read(noXyz.toStdString());
    QVERIFY(r.ok == false);
}

void TestPixelTo3D::plyReaderSkipsNonVertexScalarProperties()
{
    // A non-vertex element (face) declared *before* the vertex element, with
    // scalar (non-list) properties, must not be collected as vertex properties.
    // Regression: the old parser tracked element association via a 0-initialized
    // vertexCount, which made it collect face scalar properties and mis-parse xyz.
    QTemporaryDir dir;
    QVERIFY(dir.isValid());
    const QString path = dir.path() + QStringLiteral("/face_first.ply");
    QFile f(path);
    QVERIFY(f.open(QIODevice::WriteOnly | QIODevice::Text));
    f.write("ply\nformat ascii 1.0\n"
            "element face 2\n"
            "property uchar red\nproperty uchar green\nproperty uchar blue\n"
            "element vertex 3\n"
            "property float x\nproperty float y\nproperty float z\n"
            "end_header\n"
            "1.0 2.0 3.0\n4.0 5.0 6.0\n7.0 8.0 9.0\n"
            "255 0 0\n0 255 0\n");
    f.close();

    const auto r = PlyPointReader::read(path.toStdString());
    QVERIFY2(r.ok, r.error.c_str());
    QCOMPARE(r.xyz.size(), static_cast<std::size_t>(9));
    QCOMPARE(r.xyz[0], 1.0);
    QCOMPARE(r.xyz[4], 5.0);
    QCOMPARE(r.xyz[8], 9.0);
}
