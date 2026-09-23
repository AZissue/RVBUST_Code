# -*- coding: utf-8 -*-
"""
A1 变换链真值测试（test_transform_chain）。

跑法同 test_unit_guard.py（conda rvc python 直跑，看退出码）。
可选参数 `--allow-skip-oracle`：oracle 不可用时降级为退出码 0（默认缺失即 FAIL）。

覆盖：
  [1] 眼在手上：随机 T_base2tool + T_cam2tool + 合成点云，逐点比解析真值
      （真值 = 内联矩阵乘，未调被测函数 → 独立证据；@qa 变异测试实测对
       「乘序颠倒」与「丢平移」均有判别力）
  [2] 眼在手外：T_handeye = T_cam2base 直通分支（自洽检查，非独立证据）
  [3] K3：transform_pcd 不修改入参点云；颜色保留
  [4] merge_pointclouds 保色（禁裸 +=，K2/arch 实测）
  [5] 第三方 oracle：厂商 HandEyeSDK.dll —— **A1 唯一独立证据**。
      默认必需（缺失 → exit≠0），且必须打印 DLL 路径/版本/sha256，
      否则桌面多装一个更高版本就会静默换实现、nn_max 无法跨机比对（@qa ②）。
      A1 门限 1e-4 mm（@feas 实测 0.000076 mm）

R12（@feas）：src 定位改为「向上查找含 src/core/pcd_utils.py 的仓库根」或读
  `MCC_REPO_ROOT`，不再是硬编码 `../../../src` —— 否则只拷原型目录运行会死在
  §[4]，导致 §[5] 与「oracle 必需」判据永远执行不到。
"""

import hashlib
import os
import re
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
ALLOW_SKIP_ORACLE = "--allow-skip-oracle" in sys.argv[1:]
ORACLE_DEGRADED = False   # RG-09：降级路径要在末行与汇总里显式可见，禁裸 [ALL OK]


def check(cond: bool, label: str, detail: str = ""):
    tag = "OK  " if cond else "FAIL"
    print(f"  [{tag}] {label}" + (f" | {detail}" if detail else ""))
    if not cond:
        FAILURES.append(label)


def find_repo_root():
    """R12：向上查找含 src/core/pcd_utils.py 的目录，或读 MCC_REPO_ROOT。"""
    env = os.environ.get("MCC_REPO_ROOT")
    if env:
        cand = os.path.abspath(env)
        if os.path.isfile(os.path.join(cand, "src", "core", "pcd_utils.py")):
            return cand
        print(f"  [WARN] MCC_REPO_ROOT={env} 下无 src/core/pcd_utils.py，转向上查找")
    cur = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isfile(os.path.join(cur, "src", "core", "pcd_utils.py")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


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
    repo_root = find_repo_root()
    if repo_root is None:
        check(False, "定位 MCC 仓库根（含 src/core/pcd_utils.py）",
              "R12：请设 MCC_REPO_ROOT 或把原型放回仓库内；本项失败不再连累 §[5]")
        merge_pointclouds = None
    else:
        print(f"  [info] 仓库根 = {repo_root}")
        sys.path.insert(0, os.path.join(repo_root, "src"))
        from core.pcd_utils import merge_pointclouds
    if merge_pointclouds is not None:
        a = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
            rng.uniform(0, 100, (100, 3))))
        a.colors = o3d.utility.Vector3dVector(np.full((100, 3), 0.5))
        b = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(
            rng.uniform(0, 100, (100, 3))))  # 无色
        merge_pointclouds(a, b)
        check(a.has_colors() and len(a.colors) == 200,
              "带色+无色合并后 colors=200（裸 += 会清零）")

    print("=" * 70)
    print("[5] oracle：HandEyeSDK.dll TransformPointCloudsToRobotBase（A1 唯一独立证据）")
    oracle_ready = False
    global ORACLE_DEGRADED
    try:
        sys.path.insert(0, r"D:\RVC_SRC\hand-eye-tools")
        import handeye_sdk  # noqa
        dll = handeye_sdk._get_dll()
        dll_path = str(getattr(handeye_sdk, "_HANDEYE_DLL_PATH", "未知"))
        ver = "未知"
        m = re.search(r"RVCHandEyeCalibration_v([\d.]+)_\d+_win_release", dll_path)
        if m:
            ver = m.group(1)
        # 证据纪律（§10）：路径/版本/哈希一律程序打印，禁止人工转录
        if os.path.isfile(dll_path):
            with open(dll_path, "rb") as f:
                sha = hashlib.sha256(f.read()).hexdigest()
            size = os.path.getsize(dll_path)
            check(len(sha) == 64, "oracle sha256 长度为 64 位十六进制（程序自查）",
                  f"len={len(sha)}")
            print(f"  [info] oracle 路径 = {dll_path}")
            print(f"  [info] oracle 版本 = v{ver}  大小 = {size} B")
            print(f"  [info] oracle sha256 = {sha}")
        else:
            check(False, "oracle DLL 文件存在", dll_path)
        oracle_ready = True
    except Exception as e:
        dll = None
        print(f"  [ORACLE SKIPPED] oracle 不可用（handeye_sdk/DLL 缺失）：{e}")
        if not ALLOW_SKIP_ORACLE:
            check(False, "oracle 必需（缺失 → exit≠0；显式降级用 --allow-skip-oracle）",
                  "§[5] 是 A1 唯一独立证据，skip 不等于 pass（@qa ③）")
        else:
            ORACLE_DEGRADED = True

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
    if FAILURES:
        print(f"[FAILED] {len(FAILURES)} 项失败:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    if ORACLE_DEGRADED:
        # RG-09（@feas）：降级路径禁止打印裸 [ALL OK]——只看 ALL OK / 只看退出码的
        # CI 与第三方脚本会踩回 RG-01 同一个坑。降级必须在末行与汇总里显式可见。
        print("[ALL OK — 已降级：A1 独立判据(§[5] oracle) 未执行] test_transform_chain")
        print("[降级汇总] oracle 未运行（--allow-skip-oracle）：本份输出**不含 A1 唯一"
              "独立证据**，不得当作完整 A1 通过；请在有机器的环境复跑。")
    else:
        print("[ALL OK] test_transform_chain")
    sys.exit(0)


if __name__ == "__main__":
    main()
