#include "node_titles.h"

#include <map>

namespace app {

QString nodeTitle(const std::string& type, bool zh) {
    static const std::map<std::string, QString> en = {
        {"load_cloud", "Load Cloud"},   {"save_cloud", "Save Cloud"},
        {"remove_invalid", "Remove Invalid Points"},
        {"voxel_downsample", "Voxel Downsample"},
        {"random_downsample", "Random Downsample"},
        {"z_filter", "Z Range Filter"}, {"box_roi", "Box ROI"},
        {"roi_crop", "ROI Crop"},       {"display3d", "Display 3D"},
        {"plane_detect", "Plane Detection"},
        {"dbscan", "DBSCAN Clustering"},
        {"euclidean_cluster", "Euclidean Clustering"}};
    if (!zh) {
        const auto it = en.find(type);
        return it == en.end() ? QString::fromStdString(type) : it->second;
    }
    static const std::map<std::string, QString> map = {
        {"load_cloud", "点云加载"},       {"save_cloud", "保存点云"},
        {"remove_invalid", "移除无效点"}, {"voxel_downsample", "体素下采样"},
        {"random_downsample", "随机下采样"}, {"z_filter", "Z范围过滤"},
        {"box_roi", "Box ROI"},         {"roi_crop", "ROI裁剪"},
        {"display3d", "3D显示"},
        {"plane_detect", "平面检测"},     {"dbscan", "DBSCAN聚类"},
        {"euclidean_cluster", "欧几里得聚类"}};
    const auto it = map.find(type);
    return it == map.end() ? QString::fromStdString(type) : it->second;
}

QString categoryTitle(const std::string& category, bool zh) {
    if (!zh) return QString::fromStdString(category);
    if (category == "IO") return "输入输出";
    if (category == "Filters") return "过滤器";
    if (category == "Segmentation") return "分割";
    if (category == "Clustering") return "聚类";
    if (category == "ROI") return "ROI";
    if (category == "Display") return "显示";
    return QString::fromStdString(category);
}

QString paramLabel(const std::string& label, bool zh) {
    if (!zh) return QString::fromStdString(label);
    static const std::map<std::string, QString> map = {
        {"File Path", "文件路径"},       {"Output Path", "输出路径"},
        {"Output Folder", "输出文件夹"},  {"File Name", "文件名"},
        {"Source Unit", "源单位"},       {"Format", "格式"},
        {"Output Unit", "输出单位"},     {"Leaf Size", "体素大小"},
        {"Mode", "模式"},               {"Target Count", "目标点数"},
        {"Random Seed", "随机种子"},     {"Z Min", "Z 最小值"},
        {"Z Max", "Z 最大值"},          {"X Min", "X 最小值"},
        {"X Max", "X 最大值"},          {"Y Min", "Y 最小值"},
        {"Y Max", "Y 最大值"},          {"Viewport", "视窗"},
        {"Rotate X (deg)", "X 旋转角"},  {"Rotate Y (deg)", "Y 旋转角"},
        {"Rotate Z (deg)", "Z 旋转角"},
        {"Distance Threshold", "距离阈值"}, {"Min Inliers", "最小内点数"},
        {"Max Planes", "最大平面数"},    {"RANSAC Iterations", "RANSAC 迭代次数"},
        {"Cluster Tolerance", "聚类容差"}, {"Min Cluster Size", "最小簇大小"},
        {"Max Cluster Size", "最大簇大小"}};
    const auto it = map.find(label);
    return it == map.end() ? QString::fromStdString(label) : it->second;
}

}  // namespace app
