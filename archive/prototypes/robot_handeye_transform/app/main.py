# -*- coding: utf-8 -*-
"""
入口（批 2）。用法：

  cd D:\\RVC_SRC\\Python\\MultiCameraCalibration
  unset PYTHONPATH && export QT_QPA_PLATFORM=offscreen      # 无显示器时
  "D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/robot_handeye_transform/app/main.py
  "D:/Program Files/Anaconda/envs/rvc/python.exe" prototypes/robot_handeye_transform/app/main.py --smoke 3

  --smoke N   无人值守：自动加载手眼矩阵（手动 4×4）+ Mock 位姿序列，连拍 N 帧，
              再跑一个「米制当毫米必须被拦」的反例；退出码 0 = 全过。
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from host import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
