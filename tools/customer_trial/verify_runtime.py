"""Check a frozen MCC package's camera transport without opening a device."""
import argparse
import ctypes
import os
from pathlib import Path

TRANSPORTS = (
    'MVGigEVisionSDK.dll', 'MvUsb3vTL.dll',
    'MvProducerGEV.cti', 'MvProducerU3V.cti',
)


def verify(application):
    internal = Path(application).resolve() / '_internal'
    required = ('PyRVC.pyd', 'RVC.dll', *TRANSPORTS)
    missing = [name for name in required if not (internal / name).is_file()]
    if missing:
        raise FileNotFoundError(f'打包目录缺少 RVC 运行时文件：{", ".join(missing)}')
    system = Path(os.environ['SYSTEMROOT'])
    os.environ['PATH'] = os.pathsep.join(map(str, (system / 'System32', system)))
    with os.add_dll_directory(str(internal)):
        # Hold the library objects until all probes have completed.
        handles = [ctypes.WinDLL(str(internal / name)) for name in TRANSPORTS]
    return len(handles)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('application', type=Path)
    args = parser.parse_args()
    print(f'RVC 传输模块加载通过：{verify(args.application)}/{len(TRANSPORTS)}')
