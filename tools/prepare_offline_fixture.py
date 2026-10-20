"""Prepare portable stool frame 1/2 archives from the original capture folder."""
from pathlib import Path
import argparse
import json
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import cv2
import numpy as np
from core.marker_detector import MarkerDetector
from core.offline_fixture import DEFAULT_ROOT, digest


def prepare(source, target=DEFAULT_ROOT):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    detector = MarkerDetector()
    manifest = dict(schema=1, dataset='stool', units='mm',
                    description='凳子原始采集第1、2帧；多相机为离线双视角测试，非同步双机实测；无已知转台角度。',
                    frames=[])
    for index in (1, 2):
        image = cv2.imdecode(np.fromfile(source / f'{index}.png', dtype=np.uint8), cv2.IMREAD_COLOR)
        markers = detector.detect_3d(image, offline_ply_path=str(source / f'{index}.ply'), include_invalid=True)
        name = f'frame_{index}.zip'
        with zipfile.ZipFile(target / name, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for suffix in ('ply', 'png'):
                archive.write(source / f'{index}.{suffix}', f'{index}.{suffix}')
        manifest['frames'].append(dict(id=index, archive=name, markers=markers,
            sha256={suffix: digest(source / f'{index}.{suffix}') for suffix in ('ply', 'png')}))
        print(f'frame {index}: {len(markers)} markers, {(target / name).stat().st_size:,} archive bytes', flush=True)
    (target / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2,
        default=lambda value: value.item() if isinstance(value, np.generic) else value.tolist()), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    prepare(args.source)
