import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


@unittest.skipUnless(os.name == 'nt' and shutil.which('pwsh.exe'), 'Windows PowerShell 7 launcher')
class ScheduledLauncherTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('scheduled_launcher', Path(__file__).resolve().parents[1] / 'tools' / 'run_scheduled_hidden.py')
        self.launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.launcher)
        parent = Path(__file__).resolve().parents[1] / '.test-work'
        parent.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix='scheduled-launcher-', dir=parent)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'tools').mkdir()
        self.launcher.__file__ = str(self.root / 'tools' / 'run_scheduled_hidden.py')

    def run_launcher(self, task, powershell=None):
        with patch.object(sys, 'argv', ['launcher', '--powershell', powershell or shutil.which('pwsh.exe'), '--task', task]):
            return self.launcher.main()

    def test_child_failure_and_mode_reach_scheduler_without_losing_output(self):
        (self.root / 'tools' / 'run_scroll_background.ps1').write_text(
            "param([string]$Mode)\nWrite-Output ('selected=' + $Mode)\nexit 7\n", encoding='utf-8')
        self.assertEqual(self.run_launcher('Queue'), 7)
        log = (self.root / 'data' / 'agent' / 'scheduler' / 'queue.log').read_text(encoding='utf-8')
        self.assertIn('selected=Queue', log)

    def test_unstartable_child_is_recorded_and_reports_failure(self):
        self.assertEqual(self.run_launcher('Queue', str(self.root / 'absent.exe')), 1)
        log = (self.root / 'data' / 'agent' / 'scheduler' / 'queue.log').read_text(encoding='utf-8')
        self.assertIn('FileNotFoundError', log)

    def test_daily_route_uses_existing_runner_without_background_mode(self):
        # A temporary harmless runner: never executes the real sending workflow.
        (self.root / 'tools' / 'run_scroll_daily.ps1').write_text(
            "if ($args.Count -ne 0) { exit 9 }; Write-Output 'daily-route'; exit 0\n", encoding='utf-8')
        self.assertEqual(self.run_launcher('Daily'), 0)
        log = (self.root / 'data' / 'agent' / 'scheduler' / 'daily.log').read_text(encoding='utf-8')
        self.assertIn('daily-route', log)
