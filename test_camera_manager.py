# -*- coding: utf-8 -*-
#!/usr/bin/env python3
"""
test_camera_manager.py —— CameraManager 并发拍摄串行化测试（无 GUI、无需相机）。

背景（2026-10-09 实机故障）：两台 RVC-I540（X1, GigE）在 sync-capture 线程
并发 Capture() 时，cam1 深度数据被污染（大量飞点 + 47% 无效像素），串行
拍摄与 RVCManager 单拍均正常。根因待 prototypes/sync_capture_stress 复现
脚本进一步定位；主程序先以全局采集锁保证任意时刻只有一路采集在飞行，
用采集间隔换取数据正确。

验证：
  [1] capture_all(sync=True) 多相机并发触发时，各相机采集区间不得重叠
  [2] 串行化后所有相机仍全部完成拍摄，frame_id 一致
  [3] find_by_sn 把字符串 "None"/空串视为无 SN，不做 SN 去重（防误报）
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

print("=" * 60)
print("CameraManager 并发拍摄串行化测试")
print("=" * 60)

import numpy as np  # noqa: E402

from core.camera_manager import CameraManager, SingleCameraController  # noqa: E402
import core.camera_manager as camera_manager_mod  # noqa: E402

passed = []


def check(name: str, cond: bool, detail: str = ""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        print("\n测试失败：" + name)
        sys.exit(1)
    passed.append(name)


class FakeImage(np.ndarray):
    """模拟 RVC.Image：支持 np.array() 转换与 Clone()。"""

    def Clone(self):
        return self


class FakeSdkCamera:
    """模拟 SDK 相机句柄：Capture 期间短暂阻塞并记录在飞区间。"""

    def __init__(self, delay: float = 0.05):
        self.delay = delay

    def Capture(self, *args, **kwargs):
        _ConcurrentProbe.enter()
        try:
            time.sleep(self.delay)
        finally:
            _ConcurrentProbe.exit()
        return True

    def GetImage(self, *args):
        return np.zeros((4, 4), dtype=np.uint8).view(FakeImage)

    def GetPointMap(self):
        return self

    def Clone(self):
        return self


class FakeCamera(SingleCameraController):
    """走真实 SingleCameraController.capture_3d 锁路径的测试替身。"""

    def __init__(self, name: str, delay: float = 0.05):
        super().__init__(name)
        self.camera = FakeSdkCamera(delay)
        self.is_connected = True
        self.camera_type = "X1"
        self.intervals = []


class _ConcurrentProbe:
    """全局在飞采集计数器，用于断言串行化。"""

    _count = 0
    _peak = 0
    _lock = threading.Lock()

    @classmethod
    def enter(cls):
        with cls._lock:
            cls._count += 1
            cls._peak = max(cls._peak, cls._count)

    @classmethod
    def exit(cls):
        with cls._lock:
            cls._count -= 1

    @classmethod
    def reset(cls):
        with cls._lock:
            cls._count = 0
            cls._peak = 0


# ------------------------------------------------------------------
# [1][2] sync=True 并发触发 → 采集区间不得重叠
# ------------------------------------------------------------------
print("\n[1] capture_all(sync=True) 采集串行化")
_ConcurrentProbe.reset()
mgr = CameraManager()
mgr._cameras = {
    "cam0": FakeCamera("cam0", delay=0.05),
    "cam1": FakeCamera("cam1", delay=0.05),
    "cam2": FakeCamera("cam2", delay=0.05),
}
frames = mgr.capture_all(sync=True)
check("三台相机全部完成拍摄", len(frames) == 3, f"实际 {len(frames)}")
check("全局并发峰值 == 1（无重叠在飞采集）", _ConcurrentProbe._peak == 1,
      f"峰值 {_ConcurrentProbe._peak}")
frame_ids = {f.frame_id for f in frames.values()}
check("同步拍摄 frame_id 一致", len(frame_ids) == 1, f"实际 {frame_ids}")

# ------------------------------------------------------------------
# [3] SN 去重：字符串 "None" / 空串视为无 SN
# ------------------------------------------------------------------
print("\n[2] SN 去重对 'None'/空串不误报")
mgr2 = CameraManager()
fake_a, fake_b = FakeCamera("a"), FakeCamera("b")
fake_a.sn = "None"   # 实机现象：info.sn 为字符串 "None"
fake_b.sn = "None"
mgr2._cameras = {"camA": fake_a, "camB": fake_b}
check("find_by_sn('None') 不误报占用", mgr2.find_by_sn("None") is None)
check("find_by_sn('') 不误报占用", mgr2.find_by_sn("") is None)
fake_b.sn = "REALSN"
check("真实 SN 仍能去重", mgr2.find_by_sn("REALSN") == "camB")

# ------------------------------------------------------------------
# [3] RVC SDK 全局锁接线：采集 / 点云导出 / 编码圆检测共用同一把锁
# ------------------------------------------------------------------
print("\n[3] RVC SDK 全局锁接线")
import core.utils as core_utils  # noqa: E402
from core.frame_data import FrameData  # noqa: E402
from core import marker_detector as marker_detector_mod  # noqa: E402

check("camera_manager 使用 utils.rvc_sdk_lock",
      camera_manager_mod.rvc_sdk_lock is core_utils.rvc_sdk_lock)


class _BlockingPm:
    """假 PointMap：记录调用时事件，验证是否被锁阻塞。"""

    called = None

    def SaveWithImage(self, *args, **kwargs):
        if _BlockingPm.called:
            _BlockingPm.called.set()
        return True


def _blocked_call(fn, must_block: bool) -> bool:
    """持锁期间 fn 应阻塞；释放后应完成。返回是否符合预期。"""
    done = threading.Event()
    _BlockingPm.called = done

    def _run():
        fn()

    t = threading.Thread(target=_run)
    core_utils.rvc_sdk_lock.acquire()
    try:
        t.start()
        finished_while_held = done.wait(timeout=0.4) if must_block else True
    finally:
        core_utils.rvc_sdk_lock.release()
    t.join(timeout=5)
    if must_block:
        return (not finished_while_held) and (not t.is_alive())
    return not t.is_alive()


# frame_data.load_pointcloud_o3d 的 SaveWithImage 必须走全局锁
fd = FrameData(frame_id=1, camera_name="camX")
fd.pointmap = _BlockingPm()
fd.rvc_image = np.zeros((4, 4), dtype=np.uint8)
check("load_pointcloud_o3d 被 rvc_sdk_lock 串行化",
      _blocked_call(fd.load_pointcloud_o3d, must_block=True))

# marker_detector.detect 的 DetectCodedCircleMarker 必须走全局锁
det = marker_detector_mod.MarkerDetector()
img = np.zeros((64, 64), dtype=np.uint8)
check("detect 被 rvc_sdk_lock 串行化",
      _blocked_call(lambda: det.detect(img), must_block=True))

print("\n" + "=" * 60)
print(f"全部 {len(passed)} 项断言通过")
print("=" * 60)
