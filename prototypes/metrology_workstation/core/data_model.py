from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DataNode:
    node_id: str
    name: str
    kind: str
    parent: DataNode | None = field(default=None, repr=False)
    children: list[DataNode] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    visible: bool = True
    locked: bool = False
    status: str = "就绪"

    def add_child(self, child: DataNode) -> DataNode:
        child.parent = self
        self.children.append(child)
        return child

    @property
    def row(self) -> int:
        return self.parent.children.index(self) if self.parent else 0

    @property
    def is_asset(self) -> bool:
        return self.kind in {
            "part", "scan", "point_cloud", "mesh", "cad",
            "measurement", "analysis", "report",
        }


def node_to_dict(node: DataNode) -> dict[str, Any]:
    return {
        "node_id": node.node_id, "name": node.name, "kind": node.kind,
        "metadata": node.metadata, "visible": node.visible,
        "locked": node.locked, "status": node.status,
        "children": [node_to_dict(child) for child in node.children],
    }


def node_from_dict(data: dict[str, Any], parent: DataNode | None = None) -> DataNode:
    node = DataNode(
        str(data["node_id"]), str(data["name"]), str(data["kind"]), parent=parent,
        metadata=dict(data.get("metadata", {})), visible=bool(data.get("visible", True)),
        locked=bool(data.get("locked", False)), status=str(data.get("status", "就绪")),
    )
    for child in data.get("children", []):
        node.children.append(node_from_dict(child, node))
    return node


def make_empty_project(name: str = "未命名项目", part_number: str = "") -> DataNode:
    root = DataNode("root", "", "root")
    project = root.add_child(DataNode("project", name, "project", metadata={"工件编号": part_number, "单位": "mm"}))
    for key, label in (("parts", "工件数据"), ("scans", "扫描任务"), ("reconstruction", "三维重建"), ("models", "模型封装"), ("cad", "CAD 数据"), ("measurements", "测量任务"), ("reports", "检测报告")):
        project.add_child(DataNode(key, label, "group"))
    return root


def make_demo_project() -> DataNode:
    root = DataNode("root", "", "root")
    project = root.add_child(DataNode(
        "project", "PRJ-2026-0148", "project",
        metadata={"工件编号": "PART-A17", "创建时间": "2026-11-20 09:42", "单位": "mm"},
    ))
    groups = {}
    for key, label in (
        ("parts", "工件数据"), ("scans", "扫描任务"),
        ("reconstruction", "三维重建"), ("models", "模型封装"),
        ("cad", "CAD 数据"), ("measurements", "测量任务"),
        ("reports", "检测报告"),
    ):
        groups[key] = project.add_child(DataNode(key, label, "group"))

    groups["parts"].add_child(DataNode(
        "part_001", "Housing_A17", "part",
        metadata={"材料": "Al 6061-T6", "工件编号": "PART-A17", "检验批次": "LOT-042"},
    ))
    for index in (1, 2, 3):
        groups["scans"].add_child(DataNode(
            f"scan_{index:03d}", f"Scan_{index:03d}", "scan",
            metadata={"点数": f"{1_248_320 + index * 1840:,}", "设备": "RVC-I3360", "曝光": "8.0 ms"},
            status="已采集" if index < 3 else "已校准",
        ))
    original = groups["reconstruction"].add_child(DataNode(
        "cloud_original", "Original_PointCloud", "point_cloud",
        metadata={"点数量": "3,752,480", "文件大小": "86.4 MB", "坐标系": "扫描坐标系", "平均点间距": "0.084 mm"},
        status="原始数据",
    ))
    original.locked = True
    groups["reconstruction"].add_child(DataNode(
        "cloud_fused", "Fused_PointCloud", "point_cloud",
        metadata={"点数量": "2,846,193", "文件大小": "64.8 MB", "坐标系": "工件坐标系", "平均点间距": "0.092 mm", "来源": "Scan_001–003"},
    ))
    groups["models"].add_child(DataNode(
        "mesh_001", "Mesh_001", "mesh",
        metadata={"顶点数量": "1,423,096", "三角面数量": "2,846,192", "法线状态": "一致", "孔洞数量": "0", "模型尺寸": "182.4 × 96.2 × 48.6 mm"},
    ))
    groups["cad"].add_child(DataNode(
        "cad_001", "Housing_A17.step", "cad",
        metadata={"文件格式": "STEP AP214", "单位": "mm", "几何实体数量": "1", "变换": " datum_alignment_v2"},
    ))
    dimension = groups["measurements"].add_child(DataNode("dimensions", "尺寸测量", "group"))
    dimension.add_child(DataNode(
        "measure_001", "D-012  安装孔间距", "measurement",
        metadata={"测量类型": "点到点距离", "计算结果": "96.842 mm", "公差范围": "96.800 ± 0.050 mm", "偏差": "+0.042 mm", "判定": "合格"},
    ))
    groups["measurements"].add_child(DataNode(
        "deviation_001", "偏差分析", "analysis",
        metadata={"对齐方式": "基准特征对齐", "平均偏差": "+0.018 mm", "RMS": "0.036 mm", "覆盖率": "98.7%"},
    ))
    groups["reports"].add_child(DataNode(
        "report_001", "Inspection_Report_001", "report",
        metadata={"模板": "标准三维检测报告", "测量项目": "12", "合格项目": "12", "状态": "待导出"},
    ))
    return root
