"""Readable snapshot names; live DB identities and paths remain UUID based."""
import csv
import json
import re
from pathlib import Path
from .utils import write_json_atomic


def label(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip('. ')
    return (value or '未知')[:40]


def describe(data):
    counts = {}
    folders = {}
    rows = []
    for record in sorted(data['records'], key=lambda row:(row['created'],row['frame_id'],row['uid'])):
        kind = ('后处理结果' if record['purpose']=='后处理结果' else '拼接结果') if record['kind']=='result' else ('标定帧' if '标定' in record['purpose'] or record['purpose']=='calib' else '拼接帧')
        if record.get('intermediate_of'):
            kind = '配准中间帧'
        counts[kind] = counts.get(kind,0)+1
        stamp = re.sub(r'[^0-9]', '', record['created'])[:14] or '未知时间'
        uid = record['uid']
        name = f"{kind}_{counts[kind]:03d}_{label(record['camera'] or '融合')}_{stamp}_{uid[:8]}"
        if name in folders.values():
            name += "_"+uid
        folders[uid] = name
        rows.append((kind,counts[kind],record['frame_id'],record['camera'],record['logical_name'],record['created'],record.get('revision',0),record['status'],uid,'frames/'+name,','.join(record.get('source_ids',[]))))
    return folders, rows


def name_snapshot(directory):
    directory = Path(directory)
    data = json.loads((directory/'index.json').read_text(encoding='utf-8'))
    folders, rows = describe(data)
    for uid,name in folders.items():
        (directory/'frames'/uid).rename(directory/'frames'/name)
    data['asset_folders'] = folders
    write_json_atomic(str(directory/'index.json'),data,ensure_ascii=False,indent=2)
    with (directory/'数据清单.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(('类型','分类编号','采集编号','相机','名称','创建时间','数据版本','状态','唯一ID','相对目录','来源ID'))
        writer.writerows(rows)


def restore_snapshot(directory):
    """Only called on an isolated writable draft, never the saved snapshot."""
    directory = Path(directory)
    data = json.loads((directory/'index.json').read_text(encoding='utf-8'))
    folders = data.pop('asset_folders',None)
    if folders is None:
        return
    ids = {row['uid'] for row in data['records']}
    if not isinstance(folders,dict) or set(folders)!=ids or len(set(folders.values()))!=len(ids):
        raise ValueError('会话数据目录映射无效')
    for uid,name in folders.items():
        if (not re.fullmatch('[0-9a-f]{32}',uid) or not isinstance(name,str)
                or Path(name).name!=name or '/' in name or '\\' in name or name in ('.','..')
                or not (directory/'frames'/name).is_dir()):
            raise ValueError('会话数据目录路径无效')
    for uid,name in folders.items():
        if name != uid:
            (directory/'frames'/name).rename(directory/'frames'/uid)
    write_json_atomic(str(directory/'index.json'),data,ensure_ascii=False,indent=2)
    (directory/'数据清单.csv').unlink(missing_ok=True)
