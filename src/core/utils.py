# -*- coding: utf-8 -*-
"""
通用工具模块：日志 + 安全资源释放。

从 DualCameraFusion/src/app.py 抽取（app.py:188-219），
供 core 各模块共用，避免跨模块循环依赖。
"""

import sys
import logging
from logging.handlers import RotatingFileHandler

LOG_FILE = "MultiCameraCalibration.log"


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
