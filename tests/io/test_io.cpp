#include "pcsearch/io/point_cloud_io.h"

#include <cmath>
#include <cstdio>
#include <filesystem>
#include <iostream>
#include <string>

namespace {

using pcsearch::core::LengthUnit;
using pcsearch::core::PointCloudData;
using pcsearch::io::ReadOptions;
using pcsearch::io::readPointCloud;
using pcsearch::io::writePointCloud;

bool close(float a, float b, float tol = 1e-3f) { return std::abs(a - b) <= tol; }

PointCloudData makeCloud() {
    PointCloudData c;
    c.points.resize(6, 3);
    c.colors.resize(6, 3);
    for (int i = 0; i < 6; ++i) {
        c.points(i, 0) = static_cast<float>(i * 10);
        c.points(i, 1) = static_cast<float>(i * 20 + 1);
        c.points(i, 2) = static_cast<float>(i * 30 + 2);
        c.colors(i, 0) = static_cast<float>(i) / 6.0f;
        c.colors(i, 1) = static_cast<float>(5 - i) / 6.0f;
        c.colors(i, 2) = 0.5f;
    }
    return c;
}

int checkCloud(const PointCloudData& c, const char* tag) {
    if (c.size() != 6) {
        std::cerr << tag << ": wrong size " << c.size() << "\n";
        return 1;
    }
    for (int i = 0; i < 6; ++i) {
        if (!close(c.points(i, 0), static_cast<float>(i * 10)) ||
            !close(c.points(i, 1), static_cast<float>(i * 20 + 1)) ||
            !close(c.points(i, 2), static_cast<float>(i * 30 + 2))) {
            std::cerr << tag << ": point " << i << " got (" << c.points(i, 0) << ", "
                      << c.points(i, 1) << ", " << c.points(i, 2) << ")\n";
            return 1;
        }
    }
    return 0;
}

}  // namespace

int main() {
    int failures = 0;
    const std::filesystem::path dir =
        std::filesystem::temp_directory_path() / "pcsearch_io_test";
    std::filesystem::create_directories(dir);
    const PointCloudData src = makeCloud();

    const std::string ply_path = (dir / "roundtrip.ply").string();
    writePointCloud(ply_path, src);
    if (checkCloud(readPointCloud(ply_path), "ply") != 0) ++failures;

    ReadOptions mm_options;
    mm_options.source_unit = LengthUnit::Millimeter;
    const std::string pcd_path = (dir / "roundtrip.pcd").string();
    writePointCloud(pcd_path, src);
    if (checkCloud(readPointCloud(pcd_path, mm_options), "pcd") != 0) ++failures;

    const std::string xyz_path = (dir / "roundtrip.xyz").string();
    writePointCloud(xyz_path, src);
    if (checkCloud(readPointCloud(xyz_path, mm_options), "xyz") != 0) ++failures;

    const std::string csv_path = (dir / "roundtrip.csv").string();
    writePointCloud(csv_path, src);
    if (checkCloud(readPointCloud(csv_path, mm_options), "csv") != 0) ++failures;

    // Unit conversion: write in meters, read back in mm must equal original.
    const std::string m_path = (dir / "meters.ply").string();
    pcsearch::io::WriteOptions wopt;
    wopt.target_unit = LengthUnit::Meter;
    writePointCloud(m_path, src, wopt);
    if (checkCloud(readPointCloud(m_path), "meters") != 0) ++failures;

    std::filesystem::remove_all(dir);

    if (failures == 0) {
        std::cout << "PASS\n";
        return 0;
    }
    std::cerr << failures << " checks failed\n";
    return 1;
}
