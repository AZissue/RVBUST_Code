"""RVC 资源安全清理辅助模块（替代脆弱的 try: except: pass）。"""
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def safe_destroy(obj, destroy_fn, name: str = "resource") -> bool:
    """安全销毁 RVC 资源对象。"""
    if obj is None:
        return True
    try:
        destroy_fn(obj)
        return True
    except Exception as e:
        logger.debug(f"销毁 {name} 时发生异常（可能已失效）: {e}")
        return False


class RVCPointMapGuard:
    """RVC PointMap 的 RAII 包装（上下文管理器）。"""
    def __init__(self, pm=None):
        self.pm = pm

    def __enter__(self):
        return self.pm

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False

    def release(self):
        if self.pm is not None:
            safe_destroy(self.pm, lambda x: __import__('PyRVC').PointMap.Destroy(x), "PointMap")
            self.pm = None


class RVCImageGuard:
    """RVC Image 的 RAII 包装（上下文管理器）。"""
    def __init__(self, img=None):
        self.img = img

    def __enter__(self):
        return self.img

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
        return False

    def release(self):
        if self.img is not None:
            safe_destroy(self.img, lambda x: __import__('PyRVC').Image.Destroy(x), "Image")
            self.img = None
