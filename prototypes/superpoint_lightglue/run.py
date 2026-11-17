"""Standalone SuperPoint + LightGlue experiment in the industrial workspace."""
import argparse
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

def main():
    parser = argparse.ArgumentParser(description='SuperPoint + LightGlue 无标记拼接原型，默认启动实机工作区')
    parser.add_argument('--session', type=Path, help='离线打开保存的 MCC 会话目录或 session.json')
    parser.add_argument('--output', type=Path, help='离线实验会话保存目录（与 --session 一起使用）')
    args = parser.parse_args()
    if args.session is not None:
        from prototypes.offline_workspace import OfflineWorkspace, launch_session

        class OfflineFeatureWindow(OfflineWorkspace):
            feature_recognition_enabled = True

        return launch_session(key='superpoint_lightglue', title='SuperPoint + LightGlue 无标记拼接',
                              path=args.session, workspace_type=OfflineFeatureWindow, output=args.output)
    if args.output is not None:
        parser.error('--output 需要和 --session 一起使用')

    from main import main as launch_mcc
    from ui_v2.composition import UiComposition
    from ui_v2.main_window import MainWindowShell

    class LiveFeatureWindow(MainWindowShell):
        feature_recognition_enabled = True

    return launch_mcc(composition=UiComposition(shell_factory=LiveFeatureWindow))


if __name__ == '__main__':
    raise SystemExit(main())
