"""Use the same portable source capture as the production offline entrance."""
import numpy as np
from core.offline_fixture import load_stool
from ..core.session import CloudLayer


def load_fixture(workspace, key):
    def work():
        records = load_stool()
        return records, [CloudLayer(f'凳子视角 {frame.frame_id}', np.asarray(cloud.points),
            np.asarray(cloud.colors) if cloud.has_colors() else None,
            source=frame.offline_pointmap_path,
            observation=dict(image=frame.offline_image_path, markers=frame.markers_all,
                             frame_id=str(frame.frame_id))) for frame, cloud in records]

    def done(result):
        records, layers = result
        # Result callback runs on the UI thread after file work has completed.
        # Public observation setters reject changes while _busy is true.
        workspace._busy = False
        workspace.session.layers = layers
        workspace.session.state = 'ready'
        if key == 'multi_cam':
            for cid, (frame, _) in zip(workspace.camera_ids, records):
                workspace.set_camera_observation(cid, frame.offline_image_path, frame.markers_all)
        elif key == 'turntable':
            for index, (frame, _) in enumerate(records[:2]):
                workspace.set_calibration_frame(index, frame.offline_image_path, frame.markers_all)
        workspace._refresh(fit=True, select=0)
        workspace._dirty = False
        workspace.set_connection_status('凳子第 1、2 帧离线预览 · 未连接相机')
        workspace.log('已加载项目离线测试数据；点云尚未对齐，转台角度未知。', task='离线预览')

    workspace._run(work, done, task='加载凳子离线数据')
