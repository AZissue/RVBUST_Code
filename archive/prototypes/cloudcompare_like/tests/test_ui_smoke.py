# -*- coding: utf-8 -*-
"""
K3 UI 冒烟测试（G-K3，offscreen，不涉 ROI）。

链路：载入 → DB 树 → 可见性切换 → 后处理应用 → 导出端到端。
导出判据 = 触发后文件落地（@lead 裁定：不用"连接数 ≥1"）。

运行方式：
    cd D:/RVC_SRC/Python/MultiCameraCalibration
    QT_QPA_PLATFORM=offscreen python -m unittest prototypes.cloudcompare_like.tests.test_ui_smoke -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

# 包路径导入：与 tests/test_cc.py 同口径（项目根 + src/ 上 path）。
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
for _p in (_PROJECT_ROOT, os.path.join(_PROJECT_ROOT, "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import open3d as o3d  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication
    from prototypes.cloudcompare_like.app.cc_workspace import CloudCompareWorkspace
    _HAS_APP = True
    _APP_IMPORT_ERR = ""
except Exception as _e:  # PySide6/open3d-GUI 缺失时整组跳过
    _HAS_APP = False
    _APP_IMPORT_ERR = str(_e)


@unittest.skipUnless(_HAS_APP, f"app 层不可导入: {_APP_IMPORT_ERR}")
class TestUiSmokeExport(unittest.TestCase):
    """G-K3：导出端到端 + 取消/边界/覆盖/不污染撤销栈。"""

    def setUp(self):
        self._app = QApplication.instance() or QApplication([])
        self._ws = CloudCompareWorkspace()
        self._logs: list[tuple[str, str]] = []
        self._ws.log_message.connect(lambda m, lvl: self._logs.append((lvl, m)))
        # 写出失败弹窗在 offscreen 下会阻塞，统一打桩为记录器（判据看记录内容）
        self._errors: list[tuple[str, str]] = []
        self._ws._notify_error = lambda title, msg: self._errors.append((title, msg))

    # ------------------------------------------------------------------ 工具
    def _load_one(self, directory: str, name: str = "a.ply", n: int = 200,
                  seed: int = 5, with_color: bool = True,
                  with_normals: bool = True) -> str:
        rng = np.random.default_rng(seed)
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(rng.normal(size=(n, 3)))
        if with_color:
            pcd.colors = o3d.utility.Vector3dVector(rng.random((n, 3)))
        if with_normals:
            pcd.normals = o3d.utility.Vector3dVector(
                rng.normal(size=(n, 3)))
        path = os.path.join(directory, name)
        assert o3d.io.write_point_cloud(path, pcd)
        self._ws._load_files([path])
        return self._ws._workflow.list_cloud_nodes()[-1].node_id

    def _trigger_menu_export(self, node_id: str):
        """复刻用户右键 → 点「导出点云」（菜单动作真实触发，信号走真实接线）。"""
        item = self._ws._db_tree._node_items[node_id]
        menu = self._ws._db_tree._build_context_menu(item)
        acts = {a.text(): a for a in menu.actions()}
        self.assertIn("导出点云", acts)
        acts["导出点云"].trigger()

    def _save_dialog(self, path: str):
        """mock getSaveFileName：注入路径，绕过对话框。"""
        return mock.patch(
            "prototypes.cloudcompare_like.app.cc_workspace.QFileDialog.getSaveFileName",
            return_value=(path, "PLY 文件 (*.ply)"))

    # ------------------------------------------------------------ 端到端主链
    def test_export_end_to_end(self):
        """载入 → DB 树 → 可见性 → 后处理(法线估计) → 右键导出：文件落地+读回一致。"""
        from PySide6.QtCore import Qt
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(d, n=200)
            out = os.path.join(d, "out.ply")

            # DB 树：文件/点云两级节点就位
            self.assertEqual(len(self._ws._workflow.list_cloud_nodes()), 1)
            self.assertIn(cid, self._ws._db_tree._node_items)

            # 可见性切换（取消勾选 → 视图移除 → 再勾回）
            self._ws._db_tree._node_items[cid].setCheckState(0, Qt.Unchecked)
            self.assertNotIn(cid, self._ws._viewer._clouds)
            self._ws._db_tree._node_items[cid].setCheckState(0, Qt.Checked)
            self.assertIn(cid, self._ws._viewer._clouds)

            # 后处理应用：法线估计（零法线 → 非零）
            node = self._ws._workflow.get_node(cid)
            node.pcd.normals = o3d.utility.Vector3dVector(
                np.zeros((200, 3)))
            ok, _ = self._ws._workflow.estimate_normals(cid)
            self.assertTrue(ok)
            norms = np.asarray(node.pcd.normals)
            self.assertGreater(np.abs(norms).sum(), 0, "法线估计应产生非零法线")
            colors_before = np.asarray(node.pcd.colors).copy()
            norms_before = norms.copy()

            # 不污染撤销栈：历史栈深+游标快照相等（K3-D1'：布尔对在有前置
            # 历史时恒真无判别力，栈深可捕获"导出误入历史"变异）
            hist_before = (len(self._ws._workflow._history),
                           self._ws._workflow._history_index)
            with self._save_dialog(out):
                self._trigger_menu_export(cid)

            # --- G-K3 判据：触发后文件落地 ---
            self.assertTrue(os.path.isfile(out), "导出后文件必须落地")
            with open(out, "rb") as f:
                self.assertEqual(f.read(4), b"ply\n", "PLY 头必须合法")
            back = o3d.io.read_point_cloud(out)
            self.assertEqual(len(back.points), 200, "读回点数须与节点一致")
            self.assertEqual(len(back.colors), 200, "颜色必须随节点写出")
            self.assertTrue(np.allclose(np.asarray(back.colors),
                                        colors_before, atol=2 / 255),
                            "读回颜色应与节点颜色一致（PLY uchar 量化容差）")
            self.assertEqual(len(back.normals), 200, "法线应随节点写出")
            # S1 口径：写出不得改变节点内数据
            self.assertTrue(np.allclose(np.asarray(node.pcd.normals),
                                        norms_before))
            # 不污染撤销栈
            self.assertEqual((len(self._ws._workflow._history),
                              self._ws._workflow._history_index), hist_before)
            # 成功日志可见（非静默）
            self.assertTrue(any(lvl == "success" and "已导出" in m
                                for lvl, m in self._logs))
            self.assertFalse(self._errors, "成功路径不应触发错误对话框")

    # ------------------------------------------------------------------ 取消
    def test_export_cancel_no_side_effect(self):
        """取消路径：无文件、无异常、无成功/错误日志。"""
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(d)
            out = os.path.join(d, "cancelled.ply")
            with self._save_dialog(""):
                self._trigger_menu_export(cid)
            self.assertFalse(os.path.exists(out), "取消后不得产生文件")
            self.assertFalse(self._errors)
            self.assertFalse([1 for lvl, _ in self._logs if lvl in ("success", "error")],
                             "取消不得留下成功/错误日志")

    # ------------------------------------------------------------ 非法后缀兜底
    def test_export_bad_suffix_falls_back_to_ply(self):
        """G-K3：非法后缀兜底补 .ply + 日志明示（W9/W11 不静默替换口径）。"""
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(d)
            bad = os.path.join(d, "out.txt")
            fixed = os.path.join(d, "out.ply")
            with self._save_dialog(bad):
                self._trigger_menu_export(cid)
            self.assertFalse(os.path.exists(bad))
            self.assertTrue(os.path.isfile(fixed), "兜底后 .ply 必须落地")
            self.assertTrue(any(lvl == "warn" and "已按 PLY 导出" in m
                                for lvl, m in self._logs),
                            "兜底替换必须在日志明示")

    # ------------------------------------------------------------ 写出失败明示
    def test_export_write_failure_notifies(self):
        """G-K3：写出失败 → 日志 + 对话框明示，禁吞异常。"""
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(d)
            # 指向不存在目录下的文件 → open3d 写出失败
            bad_path = os.path.join(d, "no_such_dir", "out.ply")
            with self._save_dialog(bad_path):
                self._trigger_menu_export(cid)
            self.assertFalse(os.path.exists(bad_path))
            self.assertTrue(any(lvl == "error" for lvl, _ in self._logs),
                            "写出失败必须有 error 日志")
            self.assertEqual(len(self._errors), 1, "写出失败必须弹错误对话框")
            self.assertEqual(self._errors[0][0], "导出失败")

    # ------------------------------------------------------------ 覆盖 / 可重复
    def test_export_overwrite_same_path(self):
        """同一目标连导两次：直接覆盖，内容确实更新（非仅文件存在）。"""
        with tempfile.TemporaryDirectory() as d:
            cid_a = self._load_one(d, "a.ply", n=150, seed=6)
            out = os.path.join(d, "same.ply")
            with self._save_dialog(out):
                self._trigger_menu_export(cid_a)
            back = o3d.io.read_point_cloud(out)
            self.assertEqual(len(back.points), 150)

            cid_b = self._load_one(d, "b.ply", n=400, seed=7)
            with self._save_dialog(out):
                self._trigger_menu_export(cid_b)
            back2 = o3d.io.read_point_cloud(out)
            self.assertEqual(len(back2.points), 400,
                             "覆盖导出后读回应是第二次的内容")

    # ------------------------------------------------------------ file 节点边界
    def test_export_file_node_rejected(self):
        """file 节点走导出入口 → 明示拒绝（warn 日志），不产生文件。"""
        with tempfile.TemporaryDirectory() as d:
            cid = self._load_one(d)
            file_id = self._ws._workflow.get_node(cid).parent_id
            self.assertIsNotNone(file_id)
            with self._save_dialog(os.path.join(d, "x.ply")):
                self._ws._on_export_node(file_id)
            self.assertTrue(any(lvl == "warn" for lvl, _ in self._logs),
                            "file 节点导出必须 warn 明示")
            self.assertFalse([f for f in os.listdir(d) if f == "x.ply"])


@unittest.skipUnless(_HAS_APP, f"app 层不可导入: {_APP_IMPORT_ERR}")
class TestUiNormalsWorker(unittest.TestCase):
    """AC2/AC4：法线估计期间 Qt 事件循环存活 + 重复点击被忽略（含 1% Inf 的 50 万点云）。"""

    N = 500_000
    INF_ROWS = N // 100

    def setUp(self):
        self._app = QApplication.instance() or QApplication([])
        self._ws = CloudCompareWorkspace()
        self._logs: list[tuple[str, str]] = []
        self._ws.log_message.connect(lambda m, lvl: self._logs.append((lvl, m)))

    def _inject_inf_cloud(self) -> str:
        rng = np.random.default_rng(7)
        pts = rng.normal(size=(self.N, 3)) * 100.0
        pts[rng.choice(self.N, size=self.INF_ROWS, replace=False)] = np.inf
        pcd = o3d.geometry.PointCloud()
        pcd.points = o3d.utility.Vector3dVector(pts)
        nid = self._ws._workflow.add_cloud("inf_cloud", pcd)
        self._ws._current_node_id = nid
        return nid

    def test_event_loop_alive_during_estimate(self):
        from PySide6.QtCore import QTimer, QEventLoop
        nid = self._inject_inf_cloud()

        ticks = {"n": 0}
        timer = QTimer(self._ws)
        timer.setInterval(50)
        timer.timeout.connect(lambda: ticks.__setitem__("n", ticks["n"] + 1))
        timer.start()

        self._ws._on_estimate_normals(0.0, 30)   # 0 = 自适应半径
        worker = self._ws._normals_worker
        self.assertIsNotNone(worker)
        self.assertTrue(worker.isRunning())
        self.assertFalse(self._ws._props._btn_normals.isEnabled(), "运算中按钮必须禁用")

        # AC4：运算中重复点击不得起第二个 worker
        self._ws._on_estimate_normals(0.0, 30)
        self.assertIs(self._ws._normals_worker, worker)
        self.assertTrue(any("进行中" in m for _, m in self._logs))

        loop = QEventLoop(self._ws)
        worker.finished_normals.connect(lambda *a: loop.quit())
        QTimer.singleShot(30_000, loop.quit)     # 保险丝：30 s 必退
        loop.exec()

        self.assertIsNone(self._ws._normals_worker)
        self.assertTrue(self._ws._props._btn_normals.isEnabled(), "完成后按钮必须恢复")
        timer.stop()
        # AC2：50 ms 定时器在运算窗口内必须触发 ≥20 次（旧主线程同步实现为 0 次）
        self.assertGreaterEqual(ticks["n"], 20,
                                f"事件循环疑似被堵死（仅触发 {ticks['n']} 次）")
        # 完成口径：成功日志、剔除数可见、法线全有限、点数一致
        self.assertTrue(any(lvl == "success" and "剔除非有限点" in m
                            for lvl, m in self._logs))
        node = self._ws._workflow.get_node(nid)
        self.assertEqual(len(node.pcd.points), self.N - self.INF_ROWS)
        self.assertTrue(np.isfinite(np.asarray(node.pcd.normals)).all())
        # 撤销可用（历史已压栈）
        self.assertTrue(self._ws._workflow.can_undo())

    def test_subprocess_failure_recovers_ui(self):
        """V7：子进程崩溃（非零退出）→ 错误日志、按钮恢复、状态回 loaded、不入历史。"""
        from unittest import mock

        from PySide6.QtCore import QEventLoop, QTimer
        from prototypes.cloudcompare_like.app import cc_normals_worker as nw

        nid = self._inject_inf_cloud()
        fake = mock.Mock()
        fake.communicate.return_value = ("", "simulated subprocess crash")
        fake.returncode = 1
        with mock.patch.object(nw.subprocess, "Popen", return_value=fake):
            self._ws._on_estimate_normals(0.0, 30)
            worker = self._ws._normals_worker
            self.assertIsNotNone(worker)
            loop = QEventLoop(self._ws)
            worker.finished_normals.connect(lambda *a: loop.quit())
            QTimer.singleShot(30_000, loop.quit)
            loop.exec()

        # UI 必须回到可用态（不能卡在「处理中」）
        self.assertIsNone(self._ws._normals_worker)
        self.assertTrue(self._ws._props._btn_normals.isEnabled(), "失败后按钮必须恢复")
        self.assertEqual(self._ws.current_state(), "loaded", "失败后状态必须回 loaded")
        self.assertTrue(any(lvl == "error" and "子进程" in m for lvl, m in self._logs),
                        "子进程崩溃必须 error 日志明示")
        # 失败不得污染撤销栈 / 不得改写节点
        self.assertFalse(self._ws._workflow.can_undo())
        self.assertEqual(len(self._ws._workflow.get_node(nid).pcd.points), self.N)

    def test_undo_during_estimate_rejected_by_ui(self):
        """R4-①：processing 状态下 UI 层撤销/重做必须被拒绝（状态与历史不动）。"""
        nid = self._inject_inf_cloud()
        self._ws._on_estimate_normals(0.0, 30)
        self.assertIsNotNone(self._ws._normals_worker)
        n_before = len(self._ws._workflow.get_node(nid).pcd.points)
        self._ws._on_undo()
        self._ws._on_redo()
        self.assertEqual(self._ws.current_state(), "processing", "运算中状态不得被撤销改走")
        self.assertEqual(len(self._ws._workflow.get_node(nid).pcd.points), n_before)
        self.assertTrue(any("运算进行中" in m for _, m in self._logs))
        # 收尾：等 worker 结束，避免泄漏到其它用例
        from PySide6.QtCore import QEventLoop, QTimer
        loop = QEventLoop(self._ws)
        self._ws._normals_worker.finished_normals.connect(lambda *a: loop.quit())
        QTimer.singleShot(30_000, loop.quit)
        loop.exec()

    def test_estimate_result_never_revives_undone_state(self):
        """R4-②（verify probe_undo_race 同口径）：运算中直接 wf.undo() 绕过 UI 守卫后，
        完成回调按节点点云对象身份比对，必须把结果丢弃，不得把已撤销状态写回。"""
        from PySide6.QtCore import QEventLoop, QTimer
        nid = self._inject_inf_cloud()
        wf = self._ws._workflow
        ok, msg, _ = wf.apply_process(nid)          # 先造一条历史（剔除 Inf 行）
        self.assertTrue(ok, msg)
        self.assertEqual(len(wf.get_node(nid).pcd.points), self.N - self.INF_ROWS)
        self._ws._on_estimate_normals(0.0, 30)
        worker = self._ws._normals_worker
        self.assertIsNotNone(worker)
        ok_u, _ = wf.undo()                         # 运算中撤销（绕过 UI 守卫）
        self.assertTrue(ok_u)
        self.assertEqual(len(wf.get_node(nid).pcd.points), self.N)

        loop = QEventLoop(self._ws)
        worker.finished_normals.connect(lambda *a: loop.quit())
        QTimer.singleShot(30_000, loop.quit)
        loop.exec()

        node = wf.get_node(nid)
        self.assertEqual(len(node.pcd.points), self.N, "已撤销状态不得被估计结果复活")
        self.assertFalse(node.pcd.has_normals(), "被丢弃的结果不得写入法线")
        self.assertFalse(wf.can_undo(), "丢弃结果不得压入撤销历史")
        self.assertTrue(any("结果已丢弃" in m for _, m in self._logs))


@unittest.skipUnless(_HAS_APP, f"app 层不可导入: {_APP_IMPORT_ERR}")
class TestUiLoadSanitizeVisible(unittest.TestCase):
    """R3：载入剔除行数必须可见于 UI 日志（信号级），不能只进轮转日志文件。

    M7 变异（删载入清洗）在本组零命中 → 补此守护。
    """

    def setUp(self):
        self._app = QApplication.instance() or QApplication([])
        self._ws = CloudCompareWorkspace()
        self._logs: list[tuple[str, str]] = []
        self._ws.log_message.connect(lambda m, lvl: self._logs.append((lvl, m)))

    def test_load_dropped_rows_visible_in_ui_log(self):
        n, bad = 5000, 500
        with tempfile.TemporaryDirectory() as d:
            rng = np.random.default_rng(21)
            pts = rng.normal(size=(n, 3))
            pts[:bad] = np.inf
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(pts)
            path = os.path.join(d, "inf.ply")
            assert o3d.io.write_point_cloud(path, pcd)
            self._ws._load_files([path])
            node = self._ws._workflow.list_cloud_nodes()[-1]
            self.assertEqual(len(node.pcd.points), n - bad)
            self.assertTrue(any("剔除" in m and str(bad) in m for _, m in self._logs),
                            "剔除行数必须出现在 UI 日志/状态栏（load_from_file 消息口径）")


@unittest.skipUnless(_HAS_APP, f"app 层不可导入: {_APP_IMPORT_ERR}")
class TestUiExitRace(unittest.TestCase):
    """R1 守护：估算进行中 close()+销毁不得硬崩（修复前 0xC0000409，3/3）。

    硬崩是解释器级退出码，同进程内测不到，必须子进程跑并精确取退出码。
    """

    def test_close_during_estimate_exits_cleanly(self):
        import subprocess as sp
        import sys
        import textwrap
        script = textwrap.dedent(r'''
            import os, sys, time
            os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
            ROOT = r"D:/RVC_SRC/Python/MultiCameraCalibration"
            for p in (ROOT, os.path.join(ROOT, "src")):
                sys.path.insert(0, p)
            import numpy as np, open3d as o3d
            from PySide6.QtWidgets import QApplication
            from prototypes.cloudcompare_like.app.cc_workspace import CloudCompareWorkspace
            app = QApplication([])
            ws = CloudCompareWorkspace()
            pts = np.random.default_rng(4).normal(size=(1_500_000, 3)) * 100.0
            pcd = o3d.geometry.PointCloud()
            pcd.points = o3d.utility.Vector3dVector(pts)
            nid = ws._workflow.add_cloud("big", pcd)
            ws._current_node_id = nid
            ws._on_estimate_normals(0.0, 30)
            time.sleep(0.6)                     # 等价 verify v_exit_race2.py 模式 B
            ws.close()
            del ws
            app.processEvents()
            print("SCRIPT_END_OK")
        ''')
        r = sp.run([sys.executable, "-c", script], capture_output=True, text=True,
                   timeout=180)
        self.assertEqual(r.returncode, 0,
                         f"退出码={r.returncode:#x}（0xC0000409=线程存活时销毁）\n"
                         f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("SCRIPT_END_OK", r.stdout)


if __name__ == "__main__":
    unittest.main()
