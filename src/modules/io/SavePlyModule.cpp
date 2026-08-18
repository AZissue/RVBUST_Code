#include "SavePlyModule.h"

#include <filesystem>

#include <pcl/io/ply_io.h>

#include "modules/CloudUtils.h"

namespace rvc {
namespace {

bool isAscii(const std::string& s)
{
    for (unsigned char ch : s) {
        if (ch > 127)
            return false;
    }
    return true;
}

} // namespace

bool SavePlyModule::execute(ModuleContext& ctx)
{
    const PointCloud* cloudIn = ctx.input("cloud").get<PointCloud>();
    if (!cloudIn || !*cloudIn || (*cloudIn)->empty()) {
        ctx.log("no point cloud on input port 'cloud'");
        return false;
    }

    const std::string filePath = getString("filePath");
    if (filePath.empty()) {
        ctx.log("save file path is empty");
        return false;
    }

    const PointCloud dense = removeNaNIfNeeded(*cloudIn);

    try {
        if (isAscii(filePath)) {
            if (pcl::io::savePLYFileBinary(filePath, *dense) < 0) {
                ctx.log("failed to save PLY: " + filePath);
                return false;
            }
        } else {
            // 中文/非 ASCII 路径：PCL 的 fopen 走 ANSI 会失败，
            // 先存 ASCII 临时文件，再用 std::filesystem（宽字符路径）移动
            const std::filesystem::path tempPath =
                std::filesystem::temp_directory_path() / "rvc_saveply_tmp.ply";
            if (pcl::io::savePLYFileBinary(tempPath.string(), *dense) < 0) {
                ctx.log("failed to save PLY to temp file");
                return false;
            }
            std::filesystem::copy_file(tempPath, std::filesystem::u8path(filePath),
                                       std::filesystem::copy_options::overwrite_existing);
            std::filesystem::remove(tempPath);
        }
    } catch (const std::exception& e) {
        ctx.log(std::string("save failed: ") + e.what());
        return false;
    }

    ctx.log("saved " + std::to_string(dense->size()) + " points to " + filePath);
    return true;
}

} // namespace rvc
