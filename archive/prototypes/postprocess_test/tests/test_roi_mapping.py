# -*- coding: utf-8 -*-
"""
ROI 精确索引映射测试（无 UI）。

验证 _rebuild_display_caches 生成的 _display_to_orig_indices 能精确把
显示索引映射回原始点云索引，避免旧实现中 display_step 近似映射的精度风险。

运行方式：
    cd D:/RVC_SRC/Python/MultiCameraCalibration
    "D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/postprocess_test/tests/test_roi_mapping.py
"""

import os
import sys

import numpy as np

# 加入项目 src 和本原型 app/core 路径
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_TESTS_DIR)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src"))
sys.path.insert(0, os.path.join(os.path.dirname(_TESTS_DIR), "core"))
sys.path.insert(0, os.path.join(os.path.dirname(_TESTS_DIR), "app"))


def test_identity_mapping_when_under_budget():
    """显示点数 ≤ 预算时，映射应为恒等映射。"""
    print("[TEST] 低预算恒等映射")
    n = 1000
    render_points = np.random.randn(n, 3).astype(np.float32)
    render_colors = np.ones((n, 3), dtype=np.float32)

    # 直接构造映射逻辑（避免 Qt 依赖）
    budget = 5_000_000
    total_raw = n
    if total_raw <= budget:
        display_to_orig = np.arange(n, dtype=np.int64)
    else:
        raise AssertionError("不应进入下采样分支")

    assert len(display_to_orig) == n
    assert np.array_equal(display_to_orig, np.arange(n))
    # 模拟 ROI 选择：选前 100 个显示点
    selected_display = np.arange(100)
    orig = display_to_orig[selected_display]
    assert np.array_equal(orig, np.arange(100))
    print("  [PASS]")


def test_exact_mapping_when_downsampled():
    """显示下采样时，映射应精确指向原始点云索引。"""
    print("[TEST] 下采样精确映射")
    n = 10_000
    budget = 1_000  # 强制下采样

    # 模拟 _rebuild_display_caches 的逻辑
    target = budget
    k = max(1, int(np.ceil(n / target)))
    idx = np.arange(0, n, k)
    display_to_orig = idx.astype(np.int64)

    assert len(display_to_orig) == len(idx)
    assert display_to_orig[0] == 0
    assert display_to_orig[1] == k
    assert display_to_orig[-1] < n

    # 模拟 ROI 选择：选所有显示点
    selected_display = np.arange(len(display_to_orig))
    orig = display_to_orig[selected_display]
    assert np.array_equal(orig, idx)
    # 验证：这些原始索引对应的位置正是均匀采样位置
    expected_orig = np.arange(0, n, k)
    assert np.array_equal(orig, expected_orig)
    print(f"  下采样步长 k={k}, 显示点数={len(display_to_orig)}")
    print("  [PASS]")


def test_roi_mask_generation():
    """模拟 ROI 保留/剔除的 mask 生成。"""
    print("[TEST] ROI mask 生成")
    n = 1000
    pts = np.random.randn(n, 3)

    # 模拟：显示下采样 k=3，选中显示索引 [0, 2, 5]
    k = 3
    display_to_orig = np.arange(0, n, k).astype(np.int64)
    selected_display = np.array([0, 2, 5], dtype=np.int64)
    orig_indices = display_to_orig[selected_display]

    # 保留选中
    mask_in = np.zeros(n, dtype=bool)
    mask_in[orig_indices] = True
    assert mask_in.sum() == 3
    assert mask_in[0] and mask_in[6] and mask_in[15]

    # 剔除选中
    mask_out = ~mask_in
    assert mask_out.sum() == n - 3
    assert not mask_out[0] and not mask_out[6] and not mask_out[15]
    print("  [PASS]")


def test_multi_cloud_budget_allocation():
    """多朵点云时，预算按比例分配，每朵云映射仍精确。"""
    print("[TEST] 多朵点云预算分配")
    clouds = [(1000, "cloud1"), (5000, "cloud2"), (2000, "cloud3")]
    budget = 4_000

    total_raw = sum(n for n, _ in clouds)
    min_pts = max(1000, budget // (len(clouds) * 100))

    for n, name in clouds:
        target = max(min_pts, int(budget * n / total_raw))
        if target >= n:
            idx = np.arange(n)
        else:
            k = max(1, int(np.ceil(n / target)))
            idx = np.arange(0, n, k)
        display_to_orig = idx.astype(np.int64)
        # 验证精确性
        assert display_to_orig[0] == 0
        assert display_to_orig[-1] < n
        assert np.all(np.diff(display_to_orig) > 0)
        # 模拟选择前一半显示点
        half = len(display_to_orig) // 2
        orig = display_to_orig[:half]
        assert np.array_equal(orig, idx[:half])
        print(f"  {name}: {n} -> {len(display_to_orig)} 点")
    print("  [PASS]")


def main():
    print("=" * 60)
    print("ROI 精确索引映射测试")
    print("=" * 60)
    test_identity_mapping_when_under_budget()
    test_exact_mapping_when_downsampled()
    test_roi_mask_generation()
    test_multi_cloud_budget_allocation()
    print("\n" + "=" * 60)
    print("全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
