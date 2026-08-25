#include "pcsearch/io/point_cloud_io.h"

#include <Eigen/Core>

#include <iostream>
#include <limits>
#include <string>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "usage: pcinfo <point-cloud-file>\n";
        return 1;
    }
    try {
        const auto cloud = pcsearch::io::readPointCloud(argv[1]);
        std::int64_t invalid = 0;
        Eigen::Vector3f min = Eigen::Vector3f::Constant(std::numeric_limits<float>::max());
        Eigen::Vector3f max = Eigen::Vector3f::Constant(std::numeric_limits<float>::lowest());
        for (std::int64_t i = 0; i < cloud.size(); ++i) {
            const Eigen::Vector3f p = cloud.points.row(i);
            if (!p.allFinite()) {
                ++invalid;
                continue;
            }
            min = min.cwiseMin(p);
            max = max.cwiseMax(p);
        }
        std::cout << "points   : " << cloud.size() << "\n";
        std::cout << "invalid  : " << invalid
                  << (invalid > 0 ? " (NaN/Inf, use a cleanup filter)" : "") << "\n";
        std::cout << "colors   : " << (cloud.hasColors() ? "yes" : "no") << "\n";
        std::cout << "organized: " << (cloud.organized ? "yes" : "no") << "\n";
        if (cloud.organized) {
            std::cout << "size     : " << cloud.width << " x " << cloud.height << "\n";
        }
        if (invalid < cloud.size()) {
            std::cout << "bounds(mm): ["
                      << min.x() << ", " << min.y() << ", " << min.z() << "] .. ["
                      << max.x() << ", " << max.y() << ", " << max.z() << "]\n";
        }
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
