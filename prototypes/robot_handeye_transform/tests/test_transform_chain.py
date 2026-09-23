# -*- coding: utf-8 -*-
"""
A1 变换链真值测试（test_transform_chain）。

跑法同 test_unit_guard.py（conda rvc python 直跑，看退出码）。

覆盖：
  [1] 眼在手上：随机 T_base2tool + T_cam2tool + 合成点云，逐点比解析真值
  [2] 眼在手外：T_handeye = T_cam2base 直通分支
  [3] K3：transform_pcd 不修改入参点云；颜色保留
  [4] merge_pointclouds 保色（禁裸 +=，K2/arch 实测）
  [5] 可选第三方 oracle：厂商 HandEyeSDK.dll（handeye_sdk 可导入且 DLL
      存在才跑，否则 SKIP）——A1 门限 1e-4 mm（@feas 实测 0.000076 mm）
"""

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "core"))

import numpy as np
import open3d as o3d
from scipy.spatial.transform import Rotation

import transform_chain

FAILURES = []
SKIPPED = []


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def random_rigid(rng, t_range=(200.0, 800.0)) -> np.ndarray:
    R = Rotation.random(random_state=rng).as_matrix()
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = rng.uniform(t_range[0], t_range[1], 3) * \
        rng.choice([-1.0, 1.0], size=3)
    return T


def nn_max(a: o3d.geometry.PointCloud, b: o3d.geometry.PointCloud,
           n_sample: int = 500) -> float:
    tree = o3d.geometry.KDTreeFlann(b)
    pa = np.asarray(a.points)
    idx = np.random.default_rng(0).choice(len(pa), size=min(n_sample, len(pa)),
                                          replace=False)
    m = 0.0
    for p in pa[idx]:
        _, _, d2 = tree.search_knn_vector_3d(p, 1)
        m = max(m, float(np.sqrt(d2[0])))
    return m


def main():
    rng = np.random.default_rng(42)
    N = 5000
    p_cam = rng.uniform([-300, -200, 300], [300, 200, 700], (N, 3))

    print("=" * 70)
    print("[1] 眼在手上：T_cam2base = T_base2tool @ T_cam2tool")
    for trial in range(3):
        T_base2tool = random_rigid(rng)
        T_cam2tool = random_rigid(rng, (80.0, 200.0))
        truth = (T_base2tool @ T_cam2tool) @ np.concatenate(
            [p_cam, np.ones((N, 1))], axis=1).T
        truth = truth.T[:, :3]
        T_cb = transform_chain.compute_cam2base(True, T_cam2tool, T_base2tool)
        got = transform_chain.transform_points_mm(p_cam, T_cb)
        err = float(np.max(np.abs(got - truth)))
        check(err < 1e-9, f"trial{trial} 逐点最大偏差 < 1e-9 mm", f"err={err:.3e}")

    print("=" * 70)
    print("[2] 眼在手外：T_cam2base = T_handeye（与位姿无关）")
    for trial in range(3):
        T_cam2base = random_rigid(rng, (500.0, 3000.0))
        T_base2tool = random_rigid(rng)
        truth = transform_chain.transform_points_mm(p_cam, T_cam2base)
        T_cb = transform_chain.compute_cam2base(False, T_cam2base, T_base2tool)
        got = transform_chain.transform_points_mm(p_cam, T_cb)
        err = float(np.max(np.abs(got - truth)))
        check(err < 1e-9 and np.allclose(T_cb, T_cam2base),
              f"trial{trial} 直通分支", f"err={err:.3e}")
    try:
        transform_chain.compute_cam2base(True, np.eye(3), np.eye(4))
        check(False, "非 4×4 输入必须抛 ValueError")
    except ValueError:
        check(True, "非 4×4 输入抛 ValueError")

    print("=" * 70)
    print("[3] K3：transform_pcd 不修改入参；颜色随 copy 保留")
    src = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(p_cam))
    src.colors = o3d.utility.Vector3dVector(rng.uniform(0, 1, (N, 3)))
    before = np.asarray(src.points).copy()
    T_cb = random_rigid(rng)
    out = transform_chain.transform_pcd(src, T_cb)
    check(np.array_equal(np.asarray(src.points), before),
          "入参点云坐标不被修改")
    check(np.allclose(np.asarray(out.points),
                      transform_chain.transform_points_mm(p_cam, T_cb)),
          "输出坐标正确")
    check(out.has_colors() and len(out.colors) == N and src.has_colors(),
          "颜色随复制保留（不丢色）")

    print("=" * 70)
    print("[4] merge_pointclouds 保色（src/core/pcd_utils.py）")
    sys.path.insert(0, os.path.abspath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "src")))
    from core.pcd_utils import merge_pointclouds
    a = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
        rng.uniform(0, 100, (100, 3))))
    a.colors = o3d.utility.Vector3dVector(np.full((100, 3), 0.5))
    b = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
        rng.uniform(0, 100, (100, 3))))  # 无色
    merge_pointclouds(a, b)
    check(a.has_colors() and len(a.colors) == 200,
          "带色+无色合并后 colors=200（裸 += 会清零）")

    print("=" * 70)
    print("[5] 可选 oracle：HandEyeSDK.dll TransformPointCloudsToRobotBase")
    try:
        sys.path.insert(0, r"D:\RVC_SRC\hand-eye-tools")
        import handeye_sdk  # noqa
        dll = handeye_sdk._get_dll()
        oracle_ready = True
    except Exception as e:
        dll = None
        oracle_ready = False
        print(f"  [SKIP] oracle 不可用（handeye_sdk/DLL 缺失）：{e}")

    if oracle_ready:
        import ctypes
        work = tempfile.mkdtemp(prefix="mcc_a1_oracle_")
        try:
            folder = os.path.join(work, "clouds")
            os.makedirs(folder, exist_ok=True)

            def rotz(d):
                t = np.radians(d)
                c, s = np.cos(t), np.sin(t)
                return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], float)

            def mkT(R, t):
                M = np.eye(4)
                M[:3, :3] = R
                M[:3, 3] = np.asarray(t, float)
                return M

            T_cam2tool = mkT(rotz(15), [20.0, -10.0, 120.0])
            obj_base = rng.uniform([350, 150, 60], [450, 250, 140], (4000, 3))
            poses = []
            for i, deg in enumerate([10, 45, 80]):
                Tp = mkT(rotz(deg), [300.0 + 20 * i, 100.0, 420.0])
                poses.append(Tp)
                pc = o3d.geometry.PointCloud(
                    o3d.utility.Vector3dVector(obj_base))
                pc.transform(np.linalg.inv(Tp @ T_cam2tool))
                o3d.io.write_point_cloud(os.path.join(folder, f"cloud_{i}.ply"),
                                         pc)
            pose_file = os.path.join(folder, "poses_matrix_mm.txt")
            with open(pose_file, "w", encoding="utf-8") as f:
                for Tp in poses:
                    f.write(" ".join(f"{v:.6f}" for v in Tp.reshape(-1)) + "\n")

            mat = (ctypes.c_double * 16)(*T_cam2tool.reshape(-1))
            out_dir = os.path.join(folder, "TransformToRobotBase")
            rc = dll.TransformPointCloudsToRobotBase(
                folder.encode("utf-8"), b"poses_matrix_mm.txt", 3,
                True, True, True, True, mat)
            import glob
            files = sorted(glob.glob(os.path.join(out_dir, "cloud_*.ply")))
            check(rc == 0 and len(files) == 3, "DLL 调用 rc=0 且输出 3 帧",
                  f"rc={rc} files={len(files)}")
            for i, fp in enumerate(files):
                dll_pcd = o3d.io.read_point_cloud(fp)
                # 相机系观测（与写盘文件一致）→ 经变换链回到基座系
                pc_cam = o3d.geometry.PointCloud(
                    o3d.utility.Vector3dVector(obj_base))
                pc_cam.transform(np.linalg.inv(poses[i] @ T_cam2tool))
                core_pcd = transform_chain.transform_pcd(
                    pc_cam,
                    transform_chain.compute_cam2base(True, T_cam2tool,
                                                     poses[i]))
                err = nn_max(core_pcd, dll_pcd)
                check(err < 1e-4, f"cloud_{i} core vs DLL oracle < 1e-4 mm",
                      f"nn_max={err:.6f}")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    print("=" * 70)
    if SKIPPED:
        for s in SKIPPED:
            print(f"  [SKIP] {s}")
    if FAILURES:
        print(f"[FAILED] {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("[ALL OK] test_transform_chain")
    sys.exit(0)


if __name__ == "__main__":
    main()
