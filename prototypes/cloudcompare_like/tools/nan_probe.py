import time, numpy as np, open3d as o3d, sys
p = sys.argv[1]
t=time.perf_counter(); pcd = o3d.io.read_point_cloud(p); print(f"read={time.perf_counter()-t:.2f}s n={len(pcd.points):,}", flush=True)
pts = np.asarray(pcd.points)
bad = ~np.isfinite(pts).all(axis=1)
print(f"非有限点(NaN/Inf)行数 = {int(bad.sum()):,} / {len(pts):,}", flush=True)
t=time.perf_counter()
pcd.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(radius=10.0, max_nn=30))
print(f"estimate_normals 存活, 用时={time.perf_counter()-t:.2f}s", flush=True)
nn = np.asarray(pcd.normals)
print(f"法线非有限行数 = {int((~np.isfinite(nn).all(axis=1)).sum()):,}", flush=True)
