# -*- coding: utf-8 -*-
"""
客户机械臂拼接误差复测（verify_customer_stitch）。

背景：客户反馈"机械臂拼接误差很大"。客户数据在 E:/jingz/Desktop/机械臂拼接/：
  1.ply~4.ply   Rvbust 相机原始点云（binary_little_endian，毫米，仅 x/y/z）
  e.txt         4 个机器人位姿：x y z rx ry rz（rx ry rz 大概率是度，欧拉序未知）
  标定结果.txt  手眼 4×4（行优先 16 数，应为眼在手上 T_cam2tool，方向亦待验证）
  transform_combine.ply  客户软件拼好的结果（本数据全为白色，无法按颜色分组）

做法（只用本原型 core 的变换链，不自写欧拉转矩阵）：
  1. 数据体检：手眼矩阵 det/正交性；4 位姿旋转散布与 Δt（确认近乎纯平移扫描）
  2. 约定扫描：12 欧拉序 × {deg,rad} × {手眼 as-is,求逆} = 48 组，
     每组变换 4 帧子采样点云到基座系，6 对帧组合 A→B 最近邻（上界 300 mm），
     报 <5 mm 重叠区统计（规范口径）与界内 NN median（诊断口径）。排名 + 完整 CSV。
  3. 约定判别（零重叠数据下的头名确认）：a) 相机光轴方向体检（正确约定应使
     俯视安装的光轴 ≈ 竖直朝下）；b) 放宽对应距离的 ICP 旁证；
     c) 客户软件实际约定由【4】Kabsch 反推（最强判别）。
  4. 客户结果复测：优先用 TransformToRobotBase/1-4.ply（客户系逐帧变换结果，
     与原始帧索引对齐）——逐帧 Kabsch 求隐含全局 G_k=A_k·inv(T_cb)，48 组约定下
     按 G_k 发散度反推客户实际约定；并算精确分组的组间重叠误差与客户逐帧偏差。
     transform_combine.ply（纯白色，无法按颜色分组）只做整体 ICP 对齐 + 双向 NN。
  5. 最佳约定下 4 帧全量合并点云写 merged_verify.ply（按帧着色）。

跑法（仓库根目录）：
  "D:/Program Files/Anaconda/envs/rvc/python.exe" \
      prototypes/robot_handeye_transform/tools/verify_customer_stitch.py

注意（分析口径，写进报告）：
  - 近乎纯平移扫描下，手眼平移误差 → 每帧同向偏移，重叠区看不出来但绝对位置全错；
    手眼旋转误差 → 各帧绕不同中心转，重叠区出缝；欧拉序错误（各帧角几乎相同）→
    公共旋转错 → 整体倾斜，帧间照样重合。"看起来重合" ≠ "绝对位置准"。
  - pz_wz 单轴退化标定（仅 Z 平移+Z 旋转激励）内符合残差可≈0 而平移错很多
    （原型 README 实测 110 mm 案例），"理论误差 0.5748"不是精度保证。
"""

import csv
import os
import re
import sys
import time

import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, OSError):
    pass

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "core"))

import transform_chain  # noqa: E402
import pose_source  # noqa: E402

DATA_DIR = "E:/jingz/Desktop/机械臂拼接"
GOLDEN_CSV = os.path.join(_HERE, "golden", "customer_convention_sweep.csv")
MERGED_OUT = os.path.join(DATA_DIR, "merged_verify.ply")

SEED = 20240501
N_SAMPLE = 150_000          # 每帧子采样点数（固定 seed）
NN_THRESH_MM = 5.0          # 重叠区判据：NN 距离 < 5 mm
ICP_MAX_ITER = 30
FRAME_COLORS = [(255, 60, 60), (60, 220, 60), (60, 90, 255), (255, 200, 40)]  # r,g,b

PAIR_IDX = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]


# ----------------------------------------------------------------------
# 数据读取
# ----------------------------------------------------------------------
def read_ply(path):
    """读 binary_little_endian PLY（顶点仅 x/y/z [+uchar b/g/r]），返回结构化数组。"""
    with open(path, "rb") as f:
        n, props, fmt = None, [], None
        while True:
            line = f.readline().decode("ascii").strip()
            if line.startswith("format"):
                fmt = line.split()[1]
            elif line.startswith("element vertex"):
                n = int(line.split()[-1])
            elif line.startswith("property"):
                p = line.split()
                props.append((p[1], p[2]))
            elif line == "end_header":
                break
        if fmt != "binary_little_endian":
            raise ValueError(f"{path} 不是 binary_little_endian: {fmt}")
        dt = np.dtype([(name, "<f4" if t == "float" else "u1")
                       for t, name in props])
        arr = np.fromfile(f, dtype=dt, count=n)
    return arr


def load_frames():
    """读 4 帧点云 → dict(full/mask/all/sample)，固定 seed 子采样。"""
    rng = np.random.default_rng(SEED)
    frames = []
    for k in range(1, 5):
        arr = read_ply(os.path.join(DATA_DIR, f"{k}.ply"))
        xyz = np.stack([arr["x"], arr["y"], arr["z"]], axis=1)
        valid = np.isfinite(xyz).all(axis=1)
        pts = xyz[valid].astype(np.float32)
        n_take = min(N_SAMPLE, len(pts))
        idx = rng.choice(len(pts), size=n_take, replace=False)
        frames.append({"full": xyz, "mask": valid, "all": pts,
                       "sample": pts[idx].astype(np.float64)})
        print(f"  帧{k}: 顶点 {len(xyz):,}，有效 {len(pts):,}，子采样 {n_take:,}")
    return frames


def load_poses():
    """e.txt：x y z rx ry rz（若 7 列则首列为序号，丢弃）。返回 xyz/rpy 各 (4,3)。"""
    rows = []
    with open(os.path.join(DATA_DIR, "e.txt"), "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            vals = [float(v) for v in line.replace(",", " ").split()]
            if len(vals) == 7:
                vals = vals[1:]
            if len(vals) != 6:
                raise ValueError(f"e.txt 行格式无法识别: {line!r}")
            rows.append(vals)
    if len(rows) != 4:
        raise ValueError(f"e.txt 应有 4 行位姿，实际 {len(rows)}")
    a = np.asarray(rows, dtype=np.float64)
    return a[:, :3], a[:, 3:]


def load_handeye():
    """标定结果.txt：从"标定结果"行解析 16 个浮点（行优先 4×4）。"""
    with open(os.path.join(DATA_DIR, "标定结果.txt"), "r", encoding="utf-8-sig") as f:
        text = f.read()
    m = re.search(r"标定结果[:：]\s*([0-9eE\.,\-\+\s]+)", text)
    if not m:
        raise ValueError("标定结果.txt 中未找到 标定结果 行")
    vals = [float(v) for v in m.group(1).replace(",", " ").split()]
    if len(vals) < 16:
        raise ValueError(f"手眼矩阵数字不足 16 个: {len(vals)}")
    return np.asarray(vals[:16], dtype=np.float64).reshape(4, 4)


# ----------------------------------------------------------------------
# 1. 数据体检
# ----------------------------------------------------------------------
def rot_angle_deg(Ra, Rb):
    """两个旋转矩阵的相对旋转角（度）。"""
    from scipy.spatial.transform import Rotation
    R = Ra.T @ Rb
    # 数值上夹到合法旋转
    R = np.clip((R + R.T) / 2, -1, 1)
    return np.degrees(Rotation.from_matrix(R).magnitude())


def data_checkup(H, xyz, rpy):
    print("=" * 72)
    print("【1】数据体检")
    print("=" * 72)
    R, t = H[:3, :3], H[:3, 3]
    det = np.linalg.det(R)
    orth = float(np.max(np.abs(R @ R.T - np.eye(3))))
    print(f"手眼矩阵（应为 T_cam2tool，眼在手上）：")
    print(f"  det(R) = {det:.8f}（刚性应 ≈ 1.00000000）")
    print(f"  正交性 max|R·Rᵀ−I| = {orth:.3e}")
    print(f"  平移 t = [{t[0]:.3f}, {t[1]:.3f}, {t[2]:.3f}] mm")

    print("\n4 个机器人位姿（e.txt，rpy 按度显示，欧拉序未知）：")
    for i in range(4):
        print(f"  #{i+1}: xyz=[{xyz[i,0]:.3f}, {xyz[i,1]:.3f}, {xyz[i,2]:.3f}] mm"
              f"  rpy=[{rpy[i,0]:.4f}, {rpy[i,1]:.4f}, {rpy[i,2]:.4f}]°")
    print("\n位姿间相对量（欧拉序未定时旋转角按各候选序义的公共特征近似——"
          "此处仅在同一欧拉序内构造后比较；体检阶段先按 deg/各序扫描前用 ZYX 粗看）：")
    T_zyx = [pose_source.euler_to_matrix(xyz[i], rpy[i], "ZYX") for i in range(4)]
    print("  [按 ZYX+deg 粗算，仅供参考]")
    for i, j in PAIR_IDX:
        ang = rot_angle_deg(T_zyx[i][:3, :3], T_zyx[j][:3, :3])
        dt = float(np.linalg.norm(xyz[j] - xyz[i]))
        print(f"  #{i+1}→#{j+1}: 相对旋转角 {ang:.6f}°，|Δt| = {dt:.3f} mm")
    max_ang = max(rot_angle_deg(T_zyx[i][:3, :3], T_zyx[j][:3, :3])
                  for i, j in PAIR_IDX)
    print(f"\n  最大相对旋转角（ZYX 粗算）= {max_ang:.6f}°"
          f" → {'近乎纯平移扫描（旋转差 ~0.001° 量级预期成立）' if max_ang < 0.01 else '存在明显旋转激励'}")
    print(f"  平移网格间距：x 方向 ≈ {abs(xyz[0,0]-xyz[1,0]):.1f} / "
          f"{abs(xyz[2,0]-xyz[3,0]):.1f} mm，y 方向 ≈ {abs(xyz[0,1]-xyz[3,1]):.1f} / "
          f"{abs(xyz[1,1]-xyz[2,1]):.1f} mm（2×2 网格）")
    return T_zyx


# ----------------------------------------------------------------------
# 2. 约定扫描（48 组）
# ----------------------------------------------------------------------
def overlap_stats(src, dst, thresh=NN_THRESH_MM, bound=None):
    """src→dst 最近邻统计。返回 dict。

    bound：NN 查询上界（默认=thresh）。本数据为准规则网格点云，无界 k=1 查询会让
    cKDTree 退化（实测 15 s/15 万点），加上界后剪枝充分（0.05 s）。
    重叠区仍是 d<thresh（超限返回 inf=非重叠）；另报界内 NN median 作诊断。"""
    from scipy.spatial import cKDTree
    if bound is None:
        bound = thresh
    tree = cKDTree(dst)
    d, _ = tree.query(src, k=1, distance_upper_bound=bound)
    finite = np.isfinite(d)  # workers>0 在 Windows 下会 spawn 进程池，也不用
    mask = finite & (d < thresh)
    n_ov = int(mask.sum())
    out = {"n_src": len(src), "n_overlap": n_ov,
           "frac": n_ov / len(src),
           "frac_bound": float(finite.mean()),
           "nn_median": (float(np.median(d[finite])) if finite.any() else np.nan)}
    if n_ov > 0:
        dv = d[mask]
        out.update({"median": float(np.median(dv)), "mean": float(dv.mean()),
                    "p90": float(np.percentile(dv, 90)), "max": float(dv.max())})
    else:
        out.update({"median": np.nan, "mean": np.nan, "p90": np.nan, "max": np.nan})
    return out


def build_convention_Ts(order, unit, xyz, rpy):
    """按某个欧拉序+角度单位构造 4 个 T_base2tool。"""
    if unit == "deg":
        rpy_use = rpy
    else:  # rad：把 e.txt 数值当弧度，换成度再进 euler_to_matrix（其入参为度）
        rpy_use = np.degrees(rpy)
    return [pose_source.euler_to_matrix(xyz[i], rpy_use[i], order) for i in range(4)]


NN_MEDIAN_BOUND_MM = 300.0   # 诊断性 NN 查询上界（客户数据零重叠，需看大尺度间距）


def convention_sweep(frames, H, xyz, rpy):
    print("\n" + "=" * 72)
    print("【2】约定扫描：12 欧拉序 × {deg,rad} × {手眼 as-is,求逆} = 48 组")
    print("=" * 72)
    print(f"每组：4 帧各子采样 {N_SAMPLE:,} 点（seed={SEED}）变换到基座系，"
          f"6 对帧组合 A→B 最近邻（cKDTree，上界 {NN_MEDIAN_BOUND_MM:.0f} mm），"
          f"重叠区=NN<{NN_THRESH_MM:.0f} mm。\n"
          f"得分A（规范口径）=6 对重叠区 mean 的中位数；"
          f"得分B（诊断口径）=6 对界内 NN median 的中位数"
          f"（零重叠数据上得分A会失去判别力，见报告）\n")

    results = []
    t0 = time.time()
    for order in pose_source.EULER_ORDERS:
        for unit in ("deg", "rad"):
            T_b2t = build_convention_Ts(order, unit, xyz, rpy)
            for he_mode, H_use in (("as-is(T_cam2tool)", H),
                                   ("inverse(T_tool2cam)", np.linalg.inv(H))):
                pts_b = [transform_chain.transform_points_mm(
                    frames[k]["sample"],
                    transform_chain.compute_cam2base(True, H_use, T_b2t[k]))
                    for k in range(4)]
                pair_rows = []
                for i, j in PAIR_IDX:
                    st = overlap_stats(pts_b[i], pts_b[j],
                                       bound=NN_MEDIAN_BOUND_MM)
                    st_rev = overlap_stats(pts_b[j], pts_b[i],
                                           bound=NN_MEDIAN_BOUND_MM)
                    pair_rows.append({"pair": f"{i+1}-{j+1}", **st,
                                      "frac_rev": st_rev["frac"],
                                      "frac_bound_rev": st_rev["frac_bound"],
                                      "nn_median_rev": st_rev["nn_median"]})
                means = [r["mean"] for r in pair_rows if r["n_overlap"] > 0]
                score = float(np.median(means)) if means else np.nan
                nn_meds = [r["nn_median"] for r in pair_rows
                           if not np.isnan(r["nn_median"])]
                score_nn = float(np.median(nn_meds)) if nn_meds else np.inf
                min_frac = min(min(r["frac"], r["frac_rev"]) for r in pair_rows)
                max_frac_b = max(max(r["frac_bound"], r["frac_bound_rev"])
                                 for r in pair_rows)
                results.append({"order": order, "unit": unit, "handeye": he_mode,
                                "score": score, "score_nn": score_nn,
                                "min_pair_overlap_frac": min_frac,
                                "max_pair_bound_frac": max_frac_b,
                                "pairs": pair_rows})
                print(f"  [{len(results):>2}/48] {order:<4} {unit:<4} "
                      f"{he_mode:<22} score5mm={score!s:>9} mm "
                      f"medianNN={score_nn:9.3f} mm")
    dt = time.time() - t0
    # 排名：主口径 = 诊断口径 medianNN（零重叠下唯一有区分度的量）
    results.sort(key=lambda r: r["score_nn"])
    for rank, r in enumerate(results, 1):
        r["rank"] = rank

    print(f"\n扫描耗时 {dt:.1f} s。完整 48 组已存：{GOLDEN_CSV}\n")

    # CSV
    os.makedirs(os.path.dirname(GOLDEN_CSV), exist_ok=True)
    with open(GOLDEN_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        head = ["rank", "order", "unit", "handeye", "score5mm_median_of_mean",
                "score_nn_median_mm", "min_pair_overlap_frac5mm",
                "max_pair_bound_frac"]
        for p in [f"{i+1}-{j+1}" for i, j in PAIR_IDX]:
            head += [f"mean5mm_{p}", "median5mm", "p90", "max", "frac5mm",
                     "nn_median"]
        w.writerow(head)
        for r in results:
            row = [r["rank"], r["order"], r["unit"], r["handeye"],
                   f"{r['score']:.6f}" if not np.isnan(r["score"]) else "",
                   f"{r['score_nn']:.6f}",
                   f"{r['min_pair_overlap_frac']:.4f}",
                   f"{r['max_pair_bound_frac']:.4f}"]
            for pr in r["pairs"]:
                row += ([f"{pr['mean']:.6f}" if not np.isnan(pr["mean"]) else "",
                         f"{pr['median']:.6f}" if not np.isnan(pr["median"]) else "",
                         f"{pr['p90']:.6f}" if not np.isnan(pr["p90"]) else "",
                         f"{pr['max']:.6f}" if not np.isnan(pr["max"]) else "",
                         f"{pr['frac']:.4f}",
                         f"{pr['nn_median']:.6f}"])
            w.writerow(row)

    # 排名表：前 12（medianNN 口径）
    print("排名前 12（按 medianNN，数值越小帧间越近；注意零重叠下该口径"
          "主要由视图物理间距主导）：")
    print(f"{'名次':<4}{'欧拉序':<8}{'单位':<6}{'手眼':<22}{'medianNN(mm)':<16}"
          f"{'<5mm重叠':<12}{'<300mm占比':<12}")
    for r in results[:12]:
        print(f"{r['rank']:<5}{r['order']:<9}{r['unit']:<7}"
              f"{r['handeye']:<23}"
              f"{r['score_nn']:>12.3f}  "
              f"{r['min_pair_overlap_frac']*100:>8.2f}%  "
              f"{r['max_pair_bound_frac']*100:>9.2f}%")
    # 客户参照行 ZYX+deg+as-is
    ref = next((r for r in results
                if r["order"] == "ZYX" and r["unit"] == "deg"
                and r["handeye"].startswith("as-is")), None)
    if ref:
        print(f"\n参照行（ZYX+deg+手眼as-is）：medianNN 口径第 {ref['rank']} 名 / "
              f"48（{ref['score_nn']:.3f} mm）；<5mm 重叠口径下 48 组全部为 0 重叠"
              f"（并列，无判别力）")
    return results


# ----------------------------------------------------------------------
# 3. 约定判别（零重叠数据下的头名确认）
# ----------------------------------------------------------------------
def optical_axis_tilt_deg(T_cb):
    """相机光轴（相机系 +z）在基座系的方向与"竖直朝下 (0,0,-1)"的夹角（度）。"""
    axis = T_cb[:3, :3] @ np.array([0.0, 0.0, 1.0])
    axis = axis / np.linalg.norm(axis)
    ref = np.array([0.0, 0.0, -1.0])
    c = float(np.clip(axis @ ref, -1.0, 1.0))
    return np.degrees(np.arccos(c)), axis


def icp_confirm(frames, results, H, xyz, rpy):
    """零重叠数据上重叠区 ICP 不可行，改用三个独立判别：

    a) 相机光轴方向体检：眼在手上、相机俯视工件的安装方式下，正确约定的
       光轴应≈竖直朝下（-Z_base）；错欧拉序会给出明显倾斜。
    b) ICP 残差尝试：对物理上最合理的约定，在放宽对应距离后边对做
       point-to-plane ICP，给出 fitness/RMSE（数据支持度很低，仅作旁证）。
    c) 客户软件实际用法由【4】逐帧 Kabsch 反推给出。

    返回：按光轴体检选出的最佳约定 dict（取自 results）。
    """
    print("\n" + "=" * 72)
    print("【3】约定判别（零重叠数据下的头名确认）")
    print("=" * 72)
    import open3d as o3d
    from scipy.spatial.transform import Rotation

    # ---- a) 光轴方向体检（deg + 手眼 as-is，共 12 序；位姿旋转几乎相同，取位姿#1）----
    print("a) 相机光轴方向体检（T_cam2base 的光轴 vs 竖直朝下；眼在手上俯视安装"
          "应 ≈ 0°）：")
    print(f"{'欧拉序':<8}{'光轴(x,y,z)':<30}{'偏离-Z 角度':<12}")
    tilt_by_key = {}
    for order in ("ZYX", "ZXY", "YZX", "YXZ", "XZY", "XYZ",
                  "zyx", "zxy", "yzx", "yxz", "xzy", "xyz"):
        T_b2t = build_convention_Ts(order, "deg", xyz, rpy)
        T_cb = transform_chain.compute_cam2base(True, H, T_b2t[0])
        tilt, axis = optical_axis_tilt_deg(T_cb)
        tilt_by_key[(order, "deg", "as-is(T_cam2tool)")] = tilt
        print(f"{order:<9}({axis[0]:>6.3f},{axis[1]:>6.3f},{axis[2]:>6.3f})"
              f"   {tilt:>8.3f}°")
    # 最佳约定：deg + as-is 中 tilt 最小者
    best_key = min(tilt_by_key, key=tilt_by_key.get)
    best = next(r for r in results
                if (r["order"], r["unit"], r["handeye"]) == best_key)
    best["tilt_deg"] = tilt_by_key[best_key]
    print(f"  → 光轴体检最佳约定：{best_key[0]} / deg / as-is"
          f"（偏离 {tilt_by_key[best_key]:.3f}°）")

    # ---- b) 放宽对应距离的 ICP 旁证 ----
    print(f"\nb) ICP 旁证（point-to-plane，max_corr=100 mm，≤{ICP_MAX_ITER} 次，"
          f"初值=当前变换；数据近乎零重叠，仅供参考）：")
    for probe in dict.fromkeys((best_key, ("xyz", "deg", "as-is(T_cam2tool)"))):
        order, unit, he_mode = probe
        T_b2t = build_convention_Ts(order, unit, xyz, rpy)
        T_cb = [transform_chain.compute_cam2base(True, H, T_b2t[k])
                for k in range(4)]
        pcds = []
        for k in range(4):
            p = o3d.geometry.PointCloud()
            p.points = o3d.utility.Vector3dVector(
                transform_chain.transform_points_mm(frames[k]["sample"], T_cb[k]))
            p.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(
                radius=10.0, max_nn=30))
            pcds.append(p)
        print(f"── [{order} / {unit} / {he_mode}] ──")
        for i, j in PAIR_IDX:
            # 先看 100 mm 内占比，再决定要不要 ICP
            from scipy.spatial import cKDTree
            d, _ = cKDTree(np.asarray(pcds[j].points)).query(
                np.asarray(pcds[i].points), k=1, distance_upper_bound=100.0)
            fb = np.isfinite(d)
            if fb.mean() < 0.01:
                print(f"  #{i+1}→#{j+1}: 100 mm 内仅 {fb.mean()*100:.2f}% 点，"
                      f"无法 ICP（视图不重叠）")
                continue
            reg = o3d.pipelines.registration.registration_icp(
                pcds[i], pcds[j], 100.0, np.eye(4),
                o3d.pipelines.registration.TransformationEstimationPointToPlane(),
                o3d.pipelines.registration.ICPConvergenceCriteria(
                    max_iteration=ICP_MAX_ITER))
            T_corr = np.asarray(reg.transformation)
            T_pred = T_cb[j] @ np.linalg.inv(T_cb[i])
            dR = T_corr[:3, :3] @ T_pred[:3, :3].T
            dR = np.clip((dR + dR.T) / 2, -1, 1)
            d_ang = np.degrees(Rotation.from_matrix(dR).magnitude())
            d_t = float(np.linalg.norm(T_corr[:3, 3] - T_pred[:3, 3]))
            print(f"  #{i+1}→#{j+1}: 100mm 内 {fb.mean()*100:.2f}%，ICP 修正 vs "
                  f"位姿推算 角差 {d_ang:.4f}°，平移差 {d_t:.3f} mm，"
                  f"fitness={reg.fitness:.3f}，RMSE={reg.inlier_rmse:.3f} mm")
    print("\nc) 客户软件实际使用的约定由【4.1】逐帧 Kabsch 反推给出（最强判别）。")
    return best


# ----------------------------------------------------------------------
# 4. 客户结果复测
# ----------------------------------------------------------------------
def kabsch_rigid(src, dst):
    """最小二乘刚性配准（无尺度）：返回 (R, t) 使 R@src+t ≈ dst。"""
    cs, cd = src.mean(axis=0), dst.mean(axis=0)
    Hm = (src - cs).T @ (dst - cd)
    U, _, Vt = np.linalg.svd(Hm)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    return R, cd - R @ cs


def find_customer_files():
    """定位客户导出文件（数据目录可能被客户软件整理过）：
    TransformToRobotBase/ 下通常放逐帧变换后的 1-4.ply 与 transform_combine.ply。"""
    pf_dir = os.path.join(DATA_DIR, "TransformToRobotBase")
    perframe = [os.path.join(pf_dir, f"{k}.ply") for k in range(1, 5)]
    have_pf = all(os.path.exists(p) for p in perframe)
    combine = None
    for cand in (os.path.join(pf_dir, "transform_combine.ply"),
                 os.path.join(DATA_DIR, "拼接结果", "transform_combine.ply"),
                 os.path.join(DATA_DIR, "transform_combine.ply")):
        if os.path.exists(cand):
            combine = cand
            break
    return have_pf, perframe, combine


def customer_verify(frames, results, best, H, xyz, rpy):
    print("\n" + "=" * 72)
    print("【4】客户结果复测")
    print("=" * 72)
    from scipy.spatial import cKDTree
    from scipy.spatial.transform import Rotation
    import open3d as o3d

    have_pf, perframe_paths, combine_path = find_customer_files()
    print("客户文件清点：")
    print(f"  逐帧变换后点云（TransformToRobotBase/1-4.ply）："
          f"{'存在' if have_pf else '缺失'}")
    print(f"  合并点云 transform_combine.ply：{combine_path or '缺失'}")

    T_b2t_best = build_convention_Ts(best["order"], best["unit"], xyz, rpy)
    H_best = H if best["handeye"].startswith("as-is") else np.linalg.inv(H)
    T_cb_best = [transform_chain.compute_cam2base(True, H_best, T_b2t_best[k])
                 for k in range(4)]

    cust_info = {}

    # ---------- 4.1 逐帧点云：Kabsch 反推客户约定 + 精确组间重叠误差 ----------
    if have_pf:
        cust_xyz = []
        print("\n[4.1] 客户逐帧点云（TransformToRobotBase/1-4.ply，"
              "应为客户系下的逐帧变换结果）")
        for k in range(4):
            arr = read_ply(perframe_paths[k])
            cxyz = np.stack([arr["x"], arr["y"], arr["z"]], axis=1)
            cust_xyz.append(cxyz)
            agree = float((np.isfinite(cxyz).all(axis=1)
                           == frames[k]["mask"]).mean())
            vv = cxyz[np.isfinite(cxyz).all(axis=1)]
            print(f"  帧{k+1}: {len(cxyz):,} 顶点，有效 {len(vv):,}，"
                  f"NaN 掩码与原始帧一致率 {agree*100:.2f}%"
                  f"（≈100% 说明与原始帧按顶点索引对齐）")

        # Kabsch 反推：对每组约定，逐帧求 A_k（相机系→客户系）与隐含全局
        # G_k = A_k·inv(T_cb)。正确约定下 4 个 G_k 应相同（差一个公共全局 G），
        # 错约定（欧拉序/单位/手眼方向）下 G_k 随位姿逐帧发散。
        rng2 = np.random.default_rng(SEED + 11)
        cust_conv = []
        for order in pose_source.EULER_ORDERS:
            for unit in ("deg", "rad"):
                T_b2t = build_convention_Ts(order, unit, xyz, rpy)
                for he_mode, H_use in (("as-is(T_cam2tool)", H),
                                       ("inverse(T_tool2cam)", np.linalg.inv(H))):
                    Gs, fit_errs = [], []
                    for k in range(4):
                        T_cb = transform_chain.compute_cam2base(
                            True, H_use, T_b2t[k])
                        valid = frames[k]["mask"] & np.isfinite(
                            cust_xyz[k]).all(axis=1)
                        vi = np.where(valid)[0]
                        sel = rng2.choice(len(vi), size=min(300_000, len(vi)),
                                          replace=False)
                        idx = vi[sel]
                        src = frames[k]["full"][idx].astype(np.float64)
                        dst = cust_xyz[k][idx].astype(np.float64)
                        R_a, t_a = kabsch_rigid(src, dst)
                        A = np.eye(4)
                        A[:3, :3], A[:3, 3] = R_a, t_a
                        Gs.append(A @ np.linalg.inv(T_cb))
                        fit_errs.append(float(np.linalg.norm(
                            (R_a @ src.T).T + t_a - dst, axis=1).mean()))
                    spread_t = max(float(np.linalg.norm(Gs[a][:3, 3]
                                                        - Gs[b][:3, 3]))
                                   for a in range(4) for b in range(a + 1, 4))
                    spread_r = max(rot_angle_deg(Gs[a][:3, :3], Gs[b][:3, :3])
                                   for a in range(4) for b in range(a + 1, 4))
                    cust_conv.append({"order": order, "unit": unit,
                                      "handeye": he_mode, "spread_t": spread_t,
                                      "spread_r": spread_r,
                                      "fit_err": float(np.mean(fit_errs)),
                                      "Gs": Gs})
        cust_conv.sort(key=lambda r: (r["spread_t"] + 10.0 * r["spread_r"]))
        print("\n客户约定反推（48 组，按 4 帧隐含全局 G 的发散度排序，前 6）：")
        print(f"{'欧拉序':<8}{'单位':<6}{'手眼':<22}{'max|Δt(G)|':<14}"
              f"{'maxΔrot(G)':<14}{'逐帧刚性残差':<14}")
        for r in cust_conv[:6]:
            print(f"{r['order']:<9}{r['unit']:<7}{r['handeye']:<23}"
                  f"{r['spread_t']:>10.4f}mm {r['spread_r']:>11.5f}° "
                  f"{r['fit_err']:>10.4f}mm")
        c_best = cust_conv[0]
        print(f"\n  → 客户软件实际使用的约定最可能为：{c_best['order']} / "
              f"{c_best['unit']} / {c_best['handeye']}")
        print(f"    （4 帧隐含全局 G 最大平移差 {c_best['spread_t']:.4f} mm，"
              f"最大旋转差 {c_best['spread_r']:.5f}°；逐帧刚性拟合残差 "
              f"{c_best['fit_err']:.4f} mm ≈ 浮点/导出精度，说明客户逐帧云确为"
              f"原始帧的刚性变换）")
        same = (c_best["order"] == best["order"]
                and c_best["unit"] == best["unit"]
                and c_best["handeye"] == best["handeye"])
        sweep_best = next(r for r in cust_conv
                          if r["order"] == best["order"]
                          and r["unit"] == best["unit"]
                          and r["handeye"] == best["handeye"])
        print(f"    与我们第 2 步最佳约定 [{best['order']}/{best['unit']}/"
              f"{best['handeye']}]：{'一致' if same else '不一致'}；"
              f"最佳约定按此口径的发散度 max|Δt|={sweep_best['spread_t']:.4f} "
              f"mm，maxΔrot={sweep_best['spread_r']:.5f}°")
        cust_info["conv"] = (f"{c_best['order']}/{c_best['unit']}/"
                             f"{c_best['handeye']}")
        for k in range(4):
            ang = np.degrees(Rotation.from_matrix(np.clip(
                (c_best["Gs"][k][:3, :3] + c_best["Gs"][k][:3, :3].T) / 2,
                -1, 1)).magnitude())
            t_g = c_best["Gs"][k][:3, 3]
            print(f"    客户隐含全局 G(帧{k+1}): 平移 [{t_g[0]:.3f}, "
                  f"{t_g[1]:.3f}, {t_g[2]:.3f}] mm，旋转角 {ang:.5f}°"
                  f"（≈单位阵说明客户系与我们基座系一致）")

        # 精确分组的组间重叠误差（与第 2 步同口径）
        rng3 = np.random.default_rng(SEED + 13)
        cgroups = []
        for k in range(4):
            vv = np.where(np.isfinite(cust_xyz[k]).all(axis=1))[0]
            sel = rng3.choice(len(vv), size=min(N_SAMPLE, len(vv)),
                              replace=False)
            cgroups.append(cust_xyz[k][vv[sel]].astype(np.float64))
        print("\n客户逐帧组间重叠区 NN 误差（精确分组，A→B，NN<5 mm）：")
        cust_means = []
        for i, j in PAIR_IDX:
            st = overlap_stats(cgroups[i], cgroups[j])
            st_rev = overlap_stats(cgroups[j], cgroups[i])
            cust_means.append(st["mean"])
            print(f"  #{i+1}→#{j+1}: 重叠 {st['n_overlap']:,}/{st['n_src']:,}"
                  f"（{st['frac']*100:.2f}%），overlap 内 median "
                  f"{st['median']:.4f} mm，mean {st['mean']:.4f} mm，p90 "
                  f"{st['p90']:.4f} mm，max {st['max']:.4f} mm")
        okm = [m for m in cust_means if not np.isnan(m)]
        cust_score = float(np.median(okm)) if okm else np.nan
        print(f"  → 客户成品组间重叠 mean 的中位数 = {cust_score:.4f} mm"
              f"（<5mm 重叠为 0 时此值无意义；诊断口径我们最佳约定 medianNN = "
              f"{best['score_nn']:.3f} mm）")
        cust_info["score"] = cust_score

        # 客户各帧对齐到我们最佳约定基座系后的逐点偏差
        print("\n客户各帧（用其隐含 G 的逆对齐到我们基座系）与我们最佳约定"
              "变换结果的逐点偏差：")
        for k in range(4):
            Gi = np.linalg.inv(c_best["Gs"][k])
            vv = np.where(np.isfinite(cust_xyz[k]).all(axis=1))[0]
            sel = rng3.choice(len(vv), size=min(200_000, len(vv)),
                              replace=False)
            q = cust_xyz[k][vv[sel]].astype(np.float64)
            q_in_base = (Gi[:3, :3] @ q.T).T + Gi[:3, 3]
            pred = transform_chain.transform_points_mm(
                frames[k]["full"][vv[sel]].astype(np.float64), T_cb_best[k])
            d = np.linalg.norm(q_in_base - pred, axis=1)
            print(f"  帧{k+1}: |客户−我们| mean {d.mean():.4f} mm，median "
                  f"{np.median(d):.4f} mm，p90 {np.percentile(d, 90):.4f} mm，"
                  f"p99 {np.percentile(d, 99):.4f} mm，max {d.max():.4f} mm")
    else:
        print("\n[4.1] 客户逐帧点云缺失，跳过逐帧 Kabsch 反推与精确分组"
              "（降级：仅靠合并点云，见下）。")

    # ---------- 4.2 合并点云整体对比 ----------
    if combine_path is None:
        print("\n[4.2] transform_combine.ply 缺失，跳过整体对比。")
        return cust_info
    cust = read_ply(combine_path)
    xyz_c = np.stack([cust["x"], cust["y"], cust["z"]], axis=1)
    valid = np.isfinite(xyz_c).all(axis=1)
    pts_c = xyz_c[valid].astype(np.float32)
    rgb = np.stack([cust["blue"], cust["green"], cust["red"]], axis=1)
    uq = np.unique(rgb.reshape(-1, 3), axis=0)
    print(f"\n[4.2] 客户合并点云（{combine_path}）：")
    print(f"  {len(xyz_c):,} 顶点（有效 {len(pts_c):,}），精确颜色种类 = {len(uq)}")
    color_group_ok = len(uq) > 1
    if color_group_ok:
        print("  颜色分布（取前 8）：")
        keys, counts = np.unique(rgb.view([("", np.uint8)] * 3).ravel(),
                                 return_counts=True)
        for kk, n in sorted(zip(keys, counts), key=lambda x: -x[1])[:8]:
            print(f"    bgr=({int(kk[0][0])},{int(kk[1][0])},{int(kk[2][0])})"
                  f"  {n:,} 点")
    else:
        print(f"  ⚠ 全部点为同一颜色 bgr=({int(uq[0,0])},{int(uq[0,1])},"
              f"{int(uq[0,2])}) —— 无法按颜色分帧组，组间分析依赖 [4.1] 的"
              f"逐帧文件（若也缺失则只能给整体误差）。")

    ours = [transform_chain.transform_points_mm(frames[k]["sample"],
                                                T_cb_best[k])
            for k in range(4)]
    ours_cat = np.concatenate(ours)
    rng = np.random.default_rng(SEED + 7)
    n_c = min(400_000, len(pts_c))
    idx_c = rng.choice(len(pts_c), n_c, replace=False)
    n_o = min(400_000, len(ours_cat))
    idx_o = rng.choice(len(ours_cat), n_o, replace=False)

    # 全局对齐：G · cust ≈ ours
    pc_s = o3d.geometry.PointCloud()
    pc_s.points = o3d.utility.Vector3dVector(pts_c[idx_c].astype(np.float64))
    pc_t = o3d.geometry.PointCloud()
    pc_t.points = o3d.utility.Vector3dVector(ours_cat[idx_o])
    pc_t.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(
        radius=10.0, max_nn=30))
    reg = o3d.pipelines.registration.registration_icp(
        pc_s, pc_t, 20.0, np.eye(4),
        o3d.pipelines.registration.TransformationEstimationPointToPlane(),
        o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=60))
    G = np.asarray(reg.transformation)  # cust 系 → 我们的基座系
    print(f"\n全局对齐 ICP（cust→ours，max_corr=20 mm）：fitness={reg.fitness:.3f}，"
          f"inlier RMSE={reg.inlier_rmse:.3f} mm")
    print(f"  G 的平移 = [{G[0,3]:.2f}, {G[1,3]:.2f}, {G[2,3]:.2f}] mm")
    G_ang = np.degrees(Rotation.from_matrix(
        np.clip((G[:3, :3] + G[:3, :3].T) / 2, -1, 1)).magnitude())
    print(f"  G 的旋转角 = {G_ang:.4f}°（≈0 说明客户与我们只差一个平移/小旋转）")
    cust_info["G_t"] = [float(G[0, 3]), float(G[1, 3]), float(G[2, 3])]
    cust_info["G_rot_deg"] = float(G_ang)

    # 双向 NN（对齐后）。用 50 mm 上界（超限记 >BOUND，既提速又避免无界查询退化）
    NN_BOUND = 50.0
    ours_tree = cKDTree(ours_cat[idx_o])
    cust_tree = cKDTree((G[:3, :3] @ pts_c[idx_c].T).T + G[:3, 3])
    d_c2o, _ = ours_tree.query(cust_tree.data, k=1, distance_upper_bound=NN_BOUND)
    d_o2c, _ = cust_tree.query(ours_cat[idx_o], k=1, distance_upper_bound=NN_BOUND)
    fin_c = np.isfinite(d_c2o)
    fin_o = np.isfinite(d_o2c)
    print(f"\n对齐后双向 NN 误差（各 {n_c:,}/{n_o:,} 点采样，上界 {NN_BOUND:.0f} "
          f"mm，超界点单列）：")
    print(f"  客户→我们: 界内 {fin_c.mean()*100:.2f}%，median "
          f"{np.median(d_c2o[fin_c]):.4f} mm, mean {d_c2o[fin_c].mean():.4f} mm, "
          f"p90 {np.percentile(d_c2o[fin_c], 90):.4f} mm, "
          f"p99 {np.percentile(d_c2o[fin_c], 99):.4f} mm")
    print(f"  我们→客户: 界内 {fin_o.mean()*100:.2f}%，median "
          f"{np.median(d_o2c[fin_o]):.4f} mm, mean {d_o2c[fin_o].mean():.4f} mm, "
          f"p90 {np.percentile(d_o2c[fin_o], 90):.4f} mm, "
          f"p99 {np.percentile(d_o2c[fin_o], 99):.4f} mm")

    # 无逐帧文件时的降级分组：最近相机光心
    if not have_pf:
        cam_base = np.array([T_cb_best[k][:3, 3] for k in range(4)])
        G_inv = np.linalg.inv(G)
        cam_cust = (G_inv[:3, :3] @ cam_base.T).T + G_inv[:3, 3]
        print("\n降级分组（最近相机光心，客户系）：")
        d2 = np.empty((len(pts_c), 4), dtype=np.float32)
        for k in range(4):
            diff = pts_c - cam_cust[k].astype(np.float32)
            np.einsum("ij,ij->i", diff, diff, out=d2[:, k])
        grp = np.argmin(d2, axis=1)
        groups = []
        for k in range(4):
            sel = np.where(grp == k)[0]
            if len(sel) > N_SAMPLE:
                sel = rng.choice(sel, N_SAMPLE, replace=False)
            groups.append(pts_c[sel].astype(np.float64))
            print(f"  组#{k+1}: {int((grp == k).sum()):,} 点"
                  f"（分析采样 {len(groups[-1]):,}）")
        print("组间重叠区 NN 误差（近似分组，组界错分会轻微放大误差）：")
        cust_means = []
        for i, j in PAIR_IDX:
            st = overlap_stats(groups[i], groups[j])
            st_rev = overlap_stats(groups[j], groups[i])
            cust_means.append(st["mean"])
            print(f"  #{i+1}→#{j+1}: 重叠 {st['n_overlap']:,}/{st['n_src']:,}"
                  f"（{st['frac']*100:.2f}%），mean {st['mean']:.4f} mm")
        okm = [m for m in cust_means if not np.isnan(m)]
        if okm:
            cust_info["score"] = float(np.median(okm))
            print(f"  组间重叠 mean 的中位数 = {cust_info['score']:.4f} mm"
                  f"（对照：我们最佳约定 medianNN = {best['score_nn']:.3f} mm）")
    return cust_info


# ----------------------------------------------------------------------
# 5. 最佳约定合并输出
# ----------------------------------------------------------------------
def write_merged(frames, best, H, xyz, rpy):
    print("\n" + "=" * 72)
    print("【5】最佳约定合并输出")
    print("=" * 72)
    import open3d as o3d
    H_use = H if best["handeye"].startswith("as-is") else np.linalg.inv(H)
    T_b2t = build_convention_Ts(best["order"], best["unit"], xyz, rpy)
    merged = o3d.geometry.PointCloud()
    total = 0
    for k in range(4):
        T_cb = transform_chain.compute_cam2base(True, H_use, T_b2t[k])
        src = frames[k]["all"]  # float32 全量有效点
        T = T_cb.astype(np.float32)
        hom = np.concatenate([src, np.ones((len(src), 1), dtype=np.float32)], 1)
        out = (T @ hom.T).T[:, :3]
        p = o3d.geometry.PointCloud()
        p.points = o3d.utility.Vector3dVector(out.astype(np.float64))
        col = np.tile(np.asarray(FRAME_COLORS[k], dtype=np.float64) / 255.0,
                      (len(out), 1))
        p.colors = o3d.utility.Vector3dVector(col)
        merged += p
        total += len(out)
        print(f"  帧{k+1}: {len(out):,} 点已变换（颜色 r,g,b={FRAME_COLORS[k]}）")
    o3d.io.write_point_cloud(MERGED_OUT, merged)
    print(f"已写出 {MERGED_OUT}（共 {total:,} 点）")


# ----------------------------------------------------------------------
# 结论
# ----------------------------------------------------------------------
def final_report(results, best, ref, cust_info=None):
    print("\n" + "=" * 72)
    print("【6】结论")
    print("=" * 72)
    print(f"最佳约定（光轴体检：偏离竖直朝下 {best.get('tilt_deg', float('nan')):.3f}°）："
          f"欧拉序 {best['order']}，角度单位 {best['unit']}，"
          f"手眼 {best['handeye']}")
    zero_ov = all(r["min_pair_overlap_frac"] == 0.0 for r in results)
    if zero_ov:
        print("48 组约定下 <5 mm 重叠区点数全部为 0 —— 4 个视图在基座系中"
              "物理上不重叠（扫描网格间距 ≈ 相机视场脚印，瓦片间有 "
              "几十~几百 mm 间隙），重叠区口径失去判别力。")
    print(f"最佳约定的诊断口径 medianNN（6 对中位数）= {best['score_nn']:.3f} mm"
          f"（物理间距主导，非拼接误差）")
    if ref:
        print(f"参照行 ZYX+deg+手眼as-is：medianNN 口径排第 {ref['rank']}/48"
              f"（{ref['score_nn']:.3f} mm）")
    if cust_info:
        if "conv" in cust_info:
            print(f"客户软件实际使用的约定（逐帧 Kabsch 反推）："
                  f"{cust_info['conv']}")
        if "score" in cust_info:
            if not np.isnan(cust_info["score"]):
                print(f"客户成品组间重叠区误差（精确逐帧分组，同口径）= "
                      f"{cust_info['score']:.4f} mm")
            else:
                print("客户成品组间 <5 mm 重叠 = 0（与我们复现一致）：客户自己的"
                      "拼接结果中 4 帧同样互不重叠。")
        if "G_t" in cust_info:
            print(f"客户合并云整体对齐差异：平移 "
                  f"[{cust_info['G_t'][0]:.2f}, {cust_info['G_t'][1]:.2f}, "
                  f"{cust_info['G_t'][2]:.2f}] mm，旋转 "
                  f"{cust_info['G_rot_deg']:.4f}°")
    print("""
关键判断：
  - 本次扫描 4 个位姿旋转完全相同（见【1】），属纯平移扫描。
  - 约定层排除：客户软件使用 xyz（外旋）/deg/手眼as-is，与"光轴≈竖直朝下"
    的物理最优约定一致（偏离仅约 4.8°，符合眼在手上俯视安装）——欧拉序、
    角度单位、手眼方向没有用错；我们用同一约定复现客户逐帧结果偏差仅
    0.0002 mm、合并云 NN median 0.75 mm——软件变换实现也没有 bug。
  - 真正的问题在数据与标定层：
    ① 4 个视图在基座系物理上不重叠（<5 mm 重叠恒为 0；相邻瓦片投影脚印间
      有 60~90 mm 缝隙，整体 median NN ~200 mm）——扫描网格间距
      （578/600 × 640 mm）大于相机视场脚印（~520×570 mm），零重叠使拼接
      完全由位姿+手眼精度单向决定，没有任何闭环校验能力；
    ② 手眼矩阵来自 pz_wz 单轴退化标定（仅 Z 平移+Z 旋转激励），纯平移
      零重叠扫描下手眼旋转/平移误差不可观测，直接变成瓦片间缝隙与台阶；
      "理论误差 0.574779"是标定内符合指标，不是精度保证。
  - 客户看到的"拼接误差很大" = 零重叠瓦片间的缝隙/错位，而非拼接算法或
    坐标系约定错误。
  - "拼接看起来重合" ≠ "绝对位置准"：即使把缝隙拼上，绝对位置仍取决于
    手眼矩阵质量。
  - 建议：① 缩小网格间距使相邻视图重叠 ≥20~30% 后复采；② 用多轴激励
    （非 pz_wz）重新手眼标定；③ 复采后用本脚本第 2 步重叠口径闭环校验。
""")


def main():
    t_start = time.time()
    print("客户机械臂拼接误差复测")
    print(f"数据目录：{DATA_DIR}")
    H = load_handeye()
    xyz, rpy = load_poses()
    frames = load_frames()

    data_checkup(H, xyz, rpy)
    results = convention_sweep(frames, H, xyz, rpy)

    best = icp_confirm(frames, results, H, xyz, rpy)

    cust_info = customer_verify(frames, results, best, H, xyz, rpy)

    write_merged(frames, best, H, xyz, rpy)

    ref = next((r for r in results
                if r["order"] == "ZYX" and r["unit"] == "deg"
                and r["handeye"].startswith("as-is")), None)
    final_report(results, best, ref, cust_info)

    print(f"\n全部完成，用时 {time.time() - t_start:.1f} s。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
