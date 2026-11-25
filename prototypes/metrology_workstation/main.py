from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.application import run


def main() -> int:
    parser = argparse.ArgumentParser(description="Metrology Studio 半自动三维测量工作站")
    parser.add_argument("--screenshot", default="", help="启动后保存主窗口截图并退出")
    parser.add_argument("--quit-after", type=int, default=0, help="指定毫秒后退出，用于启动检查")
    args = parser.parse_args()
    return run(screenshot=args.screenshot, quit_after=args.quit_after)


if __name__ == "__main__":
    raise SystemExit(main())
