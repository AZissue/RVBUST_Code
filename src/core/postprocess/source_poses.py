"""Resolve the original frame poses for a derived DB record."""
import numpy as np


def source_poses(database, uid, path=()):
    if uid in path or uid not in database.records:
        raise ValueError('原始帧来源缺失或循环，请重新拼接')
    row = database.records[uid]
    if row.status == '来源数据已变更，请重新拼接':
        raise ValueError('来源数据已变化，请重新拼接')
    if row.parent_transforms is not None:
        if set(row.parent_transforms) != set(row.source_ids):
            raise ValueError('手动配准来源位姿不完整')
        combined = {}
        for parent_uid, value in row.parent_transforms.items():
            matrix = np.asarray(value, float)
            if (matrix.shape != (4,4) or not np.isfinite(matrix).all()
                    or not np.allclose(matrix[3], [0,0,0,1])
                    or not np.allclose(matrix[:3,:3].T @ matrix[:3,:3], np.eye(3), atol=1e-5)
                    or not np.isclose(np.linalg.det(matrix[:3,:3]),1,atol=1e-5)):
                raise ValueError('手动配准来源位姿无效')
            parent = database.records.get(parent_uid)
            if parent is not None and parent.kind == 'raw':
                if parent.pointcloud_aligned is not True:
                    raise ValueError('原始帧未确认2D对齐，不能融合')
                poses = {parent_uid:(parent.revision,np.eye(4))}
            else:
                poses = source_poses(database,parent_uid,(*path,uid))
            for key,(revision,pose) in poses.items():
                transformed = matrix @ pose
                if key in combined and not np.allclose(combined[key][1],transformed):
                    raise ValueError('同一原始帧存在不同配准位置，不能直接进行2D融合')
                combined[key] = (revision,transformed)
        return combined
    if row.registration_transform is not None:
        matrix = np.asarray(row.registration_transform, dtype=float)
        if (matrix.shape != (4,4) or not np.isfinite(matrix).all()
                or not np.allclose(matrix[3], [0,0,0,1])
                or not np.allclose(matrix[:3,:3].T @ matrix[:3,:3], np.eye(3), atol=1e-5)
                or not np.isclose(np.linalg.det(matrix[:3,:3]), 1, atol=1e-5)
                or len(row.source_ids) != 1):
            raise ValueError('ICP来源位姿无效，请重新执行精配准')
        uid_source = row.source_ids[0]
        parent = database.records.get(uid_source)
        if parent is not None and parent.kind == 'raw':
            if parent.pointcloud_aligned is not True:
                raise ValueError('原始帧未确认2D对齐，不能融合')
            poses = {uid_source: (parent.revision, np.eye(4))}
        else:
            poses = source_poses(database, uid_source, (*path, uid))
        return {key: (revision, matrix @ pose) for key, (revision, pose) in poses.items()}
    if row.source_transforms:
        if set(row.source_transforms) != set(row.source_ids):
            raise ValueError('拼接位姿与来源帧不完整，请重新拼接')
        result = {}
        for source, value in row.source_transforms.items():
            raw = database.records.get(source)
            matrix = np.asarray(value, dtype=float)
            if raw is None or raw.kind != 'raw' or raw.pointcloud_aligned is not True:
                raise ValueError('原始帧缺失或未确认2D对齐；请开启对齐重拍并重新拼接')
            if (matrix.shape != (4,4) or not np.isfinite(matrix).all() or
                    not np.allclose(matrix[3], [0,0,0,1]) or
                    not np.allclose(matrix[:3,:3].T@matrix[:3,:3],np.eye(3),atol=1e-5) or
                    not np.isclose(np.linalg.det(matrix[:3,:3]),1,atol=1e-5)):
                raise ValueError('拼接位姿无效，请重新拼接')
            result[source] = (raw.revision, matrix)
        return result
    result = {}
    for source in row.source_ids:
        for key, pose in source_poses(database, source, (*path,uid)).items():
            if key in result and not np.allclose(result[key][1],pose[1]):
                raise ValueError('来源包含不同坐标系的拼接结果，不能直接融合')
            result[key] = pose
    if not result:
        raise ValueError('该结果未保存原始帧拼接位姿，请重新执行拼接；当前模式无法提供位姿时不能使用2D融合')
    return result
