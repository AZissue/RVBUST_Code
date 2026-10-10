# -*- coding: utf-8 -*-
"""
通用工具模块：日志 + 安全资源释放。

从 DualCameraFusion/src/app.py 抽取（app.py:188-219），
供 core 各模块共用，避免跨模块循环依赖。
"""

import sys
import json
import os
import logging
import threading
from logging.handlers import RotatingFileHandler

LOG_FILE = "MultiCameraCalibration.log"

# RVC SDK 进程级互斥锁：所有 PyRVC 调用（Capture/GetImage/GetPointMap/
# SaveWithImage/DetectCodedCircleMarker 等）必须在持有本锁的上下文中执行。
# 2026-10-09 实机已两次证实该 SDK/驱动组合并发调用会损坏数据：
#   1) sync-capture 双线程并发 Capture() → cam1 深度被污染（飞点+47% 无效）；
#   2) 拼接 worker 的 SaveWithImage 与实时预览 Capture2D 并发 →
#      保存点云时进程 ntdll 堆损坏崩溃（0xc0000374，8 月以来复发 11 次）。
# 宁可串行慢，不要并发错。
rvc_sdk_lock = threading.RLock()


def setup_logger(name: str, level=logging.INFO):
    """创建带轮转文件 handler 的 logger（重复调用返回同一实例）。"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers:
        return logger
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    fh = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    if sys.stderr and sys.stderr.isatty():
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger


logger = setup_logger(__name__)


def safe_destroy(obj, destroy_fn, name="resource"):
    """安全销毁 RVC 资源对象，异常不抛出仅记录日志。"""
    if obj is None:
        return True
    try:
        destroy_fn(obj)
        return True
    except Exception as e:
        logger.debug(f"销毁 {name} 异常: {e}")
        return False


# ------------------------------------------------------------------
# 原子写：后台任务可能在写盘途中被 os._exit 终止，直接写最终路径会留半写文件。
# 统一配方：临时文件（保留原扩展名，open3d 按扩展名分派 writer）→ os.replace。
# ------------------------------------------------------------------

def atomic_tmp_path(path: str) -> str:
    """返回原子写用的临时路径：a.ply → a.tmp.ply。

    必须保留原扩展名：open3d 写 a.ply.tmp 会报 unknown file extension 且返回 False。
    """
    base, ext = os.path.splitext(path)
    return f"{base}.tmp{ext}"


def write_json_atomic(path: str, data, **kwargs):
    """JSON 原子写：先写同目录临时文件，再 os.replace 到最终路径。

    失败（json 序列化异常、写盘异常、中断）时清理临时文件后原样抛出：
    留下 `<name>.tmp.json` 会被会话加载侧的按扩展名扫描当成有效数据。
    """
    tmp = atomic_tmp_path(path)
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, **kwargs)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def write_point_cloud_atomic(path: str, pcd) -> bool:
    """点云原子写。返回是否成功。

    注意：open3d 写入失败只打 warning、返回 False，不抛异常——必须检查返回值。
    """
    import open3d as o3d
    tmp = atomic_tmp_path(path)
    ok = o3d.io.write_point_cloud(tmp, pcd)
    if not ok:
        logger.error(f"点云写入失败（open3d 返回 False）: {path}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    os.replace(tmp, path)
    return True
