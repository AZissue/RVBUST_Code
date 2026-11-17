"""Verify the prototype's live and explicit offline launch routes."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from prototypes.superpoint_lightglue import run


class LaunchTests(unittest.TestCase):
    def test_default_uses_production_launcher_and_enables_feature_recognition(self):
        with (patch.object(sys, 'argv', ['run.py']), patch('main.main', return_value=7) as app,
              patch('PySide6.QtWidgets.QFileDialog.getOpenFileName', return_value=('', ''))):
            self.assertEqual(run.main(), 7)
        from ui_v2.composition import UiComposition
        from ui_v2.main_window import MainWindowShell
        composition = app.call_args.kwargs['composition']
        self.assertIs(composition.launcher_factory, UiComposition().launcher_factory)
        self.assertTrue(issubclass(composition.shell_factory, MainWindowShell))
        self.assertTrue(composition.shell_factory.feature_recognition_enabled)
        self.assertIs(composition.shell_factory.postprocess_editor_type, MainWindowShell.postprocess_editor_type)

    def test_session_is_an_explicit_offline_route(self):
        with patch.object(sys, 'argv', ['run.py', '--session=example/session.json', '--output', 'results']), \
                patch('prototypes.offline_workspace.launch_session', return_value=6) as app:
            self.assertEqual(run.main(), 6)
        self.assertEqual(app.call_args.kwargs['path'], Path('example/session.json'))
        self.assertEqual(app.call_args.kwargs['output'], Path('results'))
        self.assertTrue(app.call_args.kwargs['workspace_type'].feature_recognition_enabled)
