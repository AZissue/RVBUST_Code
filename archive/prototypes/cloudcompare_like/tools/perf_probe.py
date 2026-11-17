import sys, time, importlib.util, os
import numpy as np
import open3d as o3d

import ctypes, ctypes.wintypes as wt
class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
def _mem():
    pmc = PMC(); pmc.cb = ctypes.sizeof(PMC)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
    return pmc.WorkingSetSize / 1e6, pmc.PeakWorkingSetSize / 1e6
def rss():
    return _mem()[0]
def peak():
    return _mem()[1]

P = r"D:\RVC_SRC\Python\MultiCameraCalibration\prototypes\cloudcompare_like\core\cc_octree_lod.py"
spec = importlib.util.spec_from_file_location("cc_octree_lod", P)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

path = sys.argv[1]
t0 = time.perf_counter()
pcd = o3d.io.read_point_cloud(path)
t_read = time.perf_counter() - t0
n = len(pcd.points)
pts = np.asarray(pcd.points)
print(f"read={t_read:.2f}s  points={n:,}  RSS={rss():.0f}MB", flush=True)
mn, mx = pts.min(axis=0), pts.max(axis=0)
print(f"bbox_min={np.round(mn,4).tolist()} bbox_max={np.round(mx,4).tolist()} extent={np.round(mx-mn,4).tolist()}", flush=True)
print(f"has_colors={pcd.has_colors()} has_normals={pcd.has_normals()} nan_rows={int(np.isnan(pts).any(axis=1).sum()):,}", flush=True)

pf = np.asarray(pts, dtype=np.float32)
cols = np.asarray(pcd.colors, dtype=np.float32)
t = time.perf_counter(); octree = m.PointCloudOctree(pf, cols); t_oct = time.perf_counter() - t
print(f"[LOD 八叉树构建] {t_oct:.2f}s  RSS={rss():.0f}MB peak={peak():.0f}MB", flush=True)

t = time.perf_counter()
pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=10.0, max_nn=30))
t_n = time.perf_counter() - t
print(f"[法线 估计 radius=10.0 max_nn=30] {t_n:.2f}s  RSS={rss():.0f}MB peak={peak():.0f}MB", flush=True)
print(f"[DONE] 总计 {t_read + t_oct + t_n:.2f}s", flush=True)
