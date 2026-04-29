"""非阻塞式 Open3D 点云预览（独立进程）。"""
import multiprocessing
import os
import tempfile

import numpy as np


def _preview_worker(ply_path: str, window_title: str, width: int, height: int):
    """在独立进程中运行 Open3D 预览。

    注意：此函数在子进程中执行，不能访问主进程的 GUI 对象。
    """
    try:
        import open3d as o3d

        pcd = o3d.io.read_point_cloud(ply_path)
        if len(pcd.points) == 0:
            return

        # 过滤 NaN / Inf
        points = np.asarray(pcd.points)
        valid_mask = np.isfinite(points).all(axis=1)
        if not valid_mask.all():
            pcd = pcd.select_by_index(np.where(valid_mask)[0])
            points = np.asarray(pcd.points)

        if len(points) == 0:
            return

        # 修复颜色
        if not pcd.has_colors():
            pcd.paint_uniform_color([1.0, 1.0, 1.0])
        else:
            colors = np.asarray(pcd.colors)
            if not np.isfinite(colors).all():
                colors = np.nan_to_num(colors, nan=0.5, posinf=1.0, neginf=0.0)
                pcd.colors = o3d.utility.Vector3dVector(colors)

        center = np.mean(points, axis=0)
        extent = np.max(points, axis=0) - np.min(points, axis=0)
        max_extent = np.max(extent)

        vis = o3d.visualization.Visualizer()
        vis.create_window(window_title=window_title, width=width, height=height)
        vis.add_geometry(pcd)

        ro = vis.get_render_option()
        ro.point_size = 3.0
        ro.background_color = np.array([0.15, 0.15, 0.15])
        ro.show_coordinate_frame = True

        vc = vis.get_view_control()
        vc.set_lookat(center)
        if max_extent > 0:
            zoom = min(0.8, 100.0 / max_extent)
            vc.set_zoom(zoom)

        vis.run()
        vis.destroy_window()
    except Exception:
        pass
    finally:
        # 清理临时文件
        try:
            if os.path.exists(ply_path):
                os.remove(ply_path)
        except Exception:
            pass


class PointCloudPreviewProcess:
    """非阻塞式 Open3D 点云预览（独立进程）。"""

    def __init__(self):
        self._process = None

    def show(self, o3d_pcd, window_title="点云预览", width=1280, height=720) -> bool:
        """在独立进程中显示点云，不阻塞 GUI 主线程。"""
        self.stop()  # 确保没有旧进程在运行

        try:
            import open3d as o3d

            # 保存为临时 PLY
            fd, tmp_path = tempfile.mkstemp(suffix=".ply")
            os.close(fd)
            o3d.io.write_point_cloud(tmp_path, o3d_pcd)

            # Windows 下 multiprocessing 需要 spawn 模式
            multiprocessing.set_start_method("spawn", force=True)

            self._process = multiprocessing.Process(
                target=_preview_worker,
                args=(tmp_path, window_title, width, height),
                daemon=True,
            )
            self._process.start()
            return True
        except Exception:
            return False

    def stop(self):
        """停止预览进程。"""
        if self._process and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=2)
            if self._process.is_alive():
                self._process.kill()
        self._process = None

    @property
    def is_running(self):
        return self._process is not None and self._process.is_alive()
