"""Transient checkbox-driven DB layers; no registration or geometry mutation."""
from PySide6.QtCore import QObject, QSignalBlocker, QTimer
from ui_common.industrial_scene.marker_display import classify_markers


class DbCloudOverlay(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.bridge = owner.bridge
        self.requested = {}
        self.cache = {}
        self._attempted_images = {}
        self._linked_images = {}
        self._running = False
        self._suppress = False

    def _workspace(self, mode):
        return {'multi_cam': self.bridge.shell.workspace_multi,
                'mobile_chain': self.bridge.shell.workspace_mobile,
                'turntable': self.bridge.shell.workspace_turntable,
                'robot_stitch': self.bridge.shell.workspace_robot}[mode]()

    def _viewer(self, mode):
        workspace = self._workspace(mode)
        return workspace.viewer() if callable(workspace.viewer) else workspace.viewer

    def _active(self, mode):
        shell = self.bridge.shell
        return (shell._presentation == 'industrial' and shell._mode == mode
                and self.bridge._current_mode == mode)

    def active(self, mode):
        return bool(self.requested.get(mode))

    def _busy(self):
        turntable = self.bridge.shell.workspace_turntable()
        return (turntable.btn_auto_capture.isChecked() or turntable._busy or
                any(worker.isRunning() and getattr(worker, '_task_name', '') not in ('db_frame_preview', 'project_export_cloud')
                    for worker in self.bridge._workers))

    def _set_checks(self, mode, ids):
        browser = self.owner.browsers.get(mode)
        if browser is None:
            return
        self._suppress = True
        try:
            with QSignalBlocker(browser.tree):
                for (uid, component), item in browser._component_items.items():
                    if component == 'cloud':
                        browser.set_component_checked(uid, component, uid in ids)
            browser._publish_checks()
        finally:
            self._suppress = False

    def reset(self, mode):
        had_request = bool(self.requested.get(mode))
        self.requested.pop(mode, None)
        self.cache.pop(mode, None)
        self._attempted_images.pop(mode, None)
        self._clear_linked_image(mode)
        self._set_checks(mode, [])
        if had_request and self._active(mode):
            self.bridge.shell._st_hint.setText('已返回工作视图')

    def drop_inactive(self, mode):
        self.reset(mode)
        self._viewer(mode).show_database_clouds({})
        self._workspace(mode)._industrial.restore_business_image()
        self.owner._preview_modes.discard(mode)

    def changed(self, mode, *, refresh=False):
        if self._suppress or getattr(self.bridge, '_cleaned', False):
            return
        browser = self.owner.browsers[mode]
        ids = [uid for uid, _ in browser.checked_components('cloud')]
        previous = self.requested.get(mode, [])
        if not ids and not previous:
            return
        if ids == previous and not refresh and mode != 'mobile_chain':
            return
        if not self._active(mode):
            self.drop_inactive(mode)
            return
        if ids == previous and not refresh:
            self._sync_linked_image(mode)
            if not self._busy():
                QTimer.singleShot(0, lambda: self._dispatch(mode))
            return
        if self._busy():
            self._set_checks(mode, self.requested.get(mode, []))
            self.bridge.shell.log('正在处理数据，请完成后勾选DB点云。', 'warn')
            return
        self.owner._selection += 1  # Invalidate an older single-frame read.
        self.requested[mode] = ids
        self._sync_linked_image(mode)
        if not ids:
            self.owner.restore(mode)
            return
        self.owner._preview_modes.add(mode)
        database = self.owner.databases[mode]
        cache = self.cache.setdefault(mode, {})
        valid = {(id(database), uid, database.records[uid].revision) for uid in ids}
        self.cache[mode] = {key: cloud for key, cloud in cache.items() if key in valid}
        self._apply(mode)
        QTimer.singleShot(40, lambda: self._dispatch(mode))

    def _image_key(self, mode):
        if mode != 'mobile_chain':
            return None
        database = self.owner.databases[mode]
        checked_clouds = self.requested.get(mode, ())
        for uid, _ in self.owner.browsers[mode].checked_components('image'):
            if uid in checked_clouds:
                return (id(database), uid, database.records[uid].revision)
        return None

    def _clear_linked_image(self, mode):
        linked = self._linked_images.pop(mode, None)
        shown = self.owner._displayed.get(mode)
        if linked and shown and shown[1] is linked[1]:
            self.owner._displayed.pop(mode, None)
            self._workspace(mode)._industrial.restore_business_image()

    def _sync_linked_image(self, mode):
        key = self._image_key(mode)
        linked = self._linked_images.get(mode)
        if linked and linked[0] != key:
            self._clear_linked_image(mode)
        if self._attempted_images.get(mode) != key:
            self._attempted_images.pop(mode, None)

    def prefer_explicit_image(self, mode):
        key = self._image_key(mode)
        if key:
            self._attempted_images[mode] = key

    def _apply(self, mode):
        if not self._active(mode):
            return
        database = self.owner.databases[mode]
        clouds = {}
        markers = []
        triangles = []
        raw = 0
        for uid in self.requested.get(mode, []):
            record = database.records.get(uid)
            if record is None:
                continue
            cloud = self.cache.get(mode, {}).get((id(database), uid, record.revision))
            if cloud is not None:
                clouds[f'{record.camera} / 帧 {record.frame_id:03d} / {uid}'] = cloud
                raw += record.kind == 'raw'
                if record.kind == 'raw':
                    display = classify_markers(record.markers)
                    # Each frame keeps its stored camera coordinates, including
                    # repeated codes at different positions across raw frames.
                    markers.extend(display.cloud_points())
                    triangle, _ = self.owner.match_geometry(mode, uid, record.markers)
                    if triangle:
                        triangles.append(triangle)
        if not clouds:
            if self._viewer(mode)._database_clouds:
                self._viewer(mode).show_database_clouds({})
            return
        viewer = self._viewer(mode)
        displayed = viewer._database_clouds
        if displayed.keys() != clouds.keys() or any(displayed[key] is not cloud for key, cloud in clouds.items()):
            viewer.show_database_clouds(clouds)
        viewer.set_cloud_markers(markers, triangles=triangles)
        shown = self.owner._displayed.get(mode)
        if not shown or shown[1].image_np is None:
            self._workspace(mode)._industrial.show_database_result()
        text = f'DB叠加预览：{len(clouds)} 帧点云'
        if raw:
            text += ' · 原始帧按各自相机坐标显示，未应用标定变换'
        self.bridge.shell._st_hint.setText(text)
        self.bridge.shell._st_hint.setToolTip(text)

    def _dispatch(self, mode):
        if getattr(self.bridge, '_cleaned', False):
            self.requested.clear()
            self.cache.clear()
            return
        if self._running or not self.requested.get(mode):
            return
        if not self._active(mode):
            self.drop_inactive(mode)
            return
        if self._busy():
            self.owner.restore(mode)
            return
        database = self.owner.databases[mode]
        missing = [(uid, database.records[uid].revision) for uid in self.requested[mode]
                   if uid in database.records and
                   (id(database), uid, database.records[uid].revision) not in self.cache.get(mode, {})]
        image_key = self._image_key(mode)
        if image_key == self._attempted_images.get(mode):
            image_key = None
        shown = self.owner._displayed.get(mode)
        if image_key and shown and shown[0] == image_key[1] and shown[1].image_np is not None:
            self._attempted_images[mode] = image_key
            image_key = None
        if not missing and image_key is None:
            return
        self._running = True
        self.bridge.shell._st_hint.setText('正在读取DB叠加预览…')

        def work():
            results = []
            for uid, revision in missing:
                try:
                    _, cloud = database.load_frame(uid, 'cloud')
                    results.append((uid, revision, cloud, None))
                except Exception as exc:
                    results.append((uid, revision, None, str(exc)))
            image, image_error = None, None
            if image_key:
                try:
                    image, _ = database.load_frame(image_key[1], 'image')
                except Exception as exc:
                    image_error = str(exc)
            return results, image, image_error

        def done(results, error):
            self._running = False
            if getattr(self.bridge, '_cleaned', False):
                self.requested.clear()
                self.cache.clear()
                return
            if not self._active(mode):
                self.drop_inactive(mode)
            elif self.owner.databases[mode] is database and self.requested.get(mode):
                failures = []
                clouds, image, image_error = results or ([], None, None)
                for uid, revision, cloud, failure in clouds:
                    record = database.records.get(uid)
                    if uid not in self.requested[mode] or record is None or record.revision != revision:
                        continue
                    if failure:
                        failures.append(uid)
                        self.bridge.shell.log(f'DB点云读取失败：{record.logical_name} · {failure}', 'error')
                    else:
                        self.cache.setdefault(mode, {})[(id(database), uid, revision)] = cloud
                if error:
                    failures = list(self.requested[mode])
                    self.bridge.shell.log('DB叠加读取失败：'+str(error), 'error')
                if failures:
                    self.requested[mode] = [uid for uid in self.requested[mode] if uid not in failures]
                    self._set_checks(mode, self.requested[mode])
                if self.requested[mode]:
                    self._apply(mode)
                    if (image_key and image_key == self._image_key(mode)
                            and self._attempted_images.get(mode) != image_key):
                        self._attempted_images[mode] = image_key
                        if image_error:
                            self.bridge.shell.log('DB关联2D图像读取失败：' + image_error, 'error')
                        elif image is not None:
                            self._linked_images[mode] = (image_key, image)
                            self.owner.display_frame(mode, image_key[1], image, None, 'image',
                                                     switch_view=False, highlight=False)
                else:
                    self.owner.restore(mode)
                    self.bridge.shell._st_hint.setText('DB点云读取失败，已返回工作视图')
            for pending in list(self.requested):
                QTimer.singleShot(0, lambda key=pending: self._dispatch(key))

        # Reuse the read-only DB task category: no archive or workflow mutation.
        self.bridge._run_background(work, done, name='db_frame_preview')
