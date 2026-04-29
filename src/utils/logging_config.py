import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_module_logger(name: str, log_file: str = "CodedCircleStitchApp.log", level=logging.INFO):
    """配置模块级 logger，不污染全局 root logger。支持日志轮转（最大5MB，保留3个备份）。"""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    if logger.handlers:
        return logger

    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')

    # 轮转文件日志（5MB per file, keep 3 backups）
    fh = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3, encoding='utf-8')
    fh.setLevel(level)
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # 仅当存在终端时输出到 stderr（避免 GUI 无意义开销）
    if sys.stderr and sys.stderr.isatty():
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(level)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger
