import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_candidate', ROOT / 'tools/build_candidate.py')
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)


class SourceDistributionTests(unittest.TestCase):
    def test_release_uses_current_readme_license_and_preserves_upstream_notice(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'candidate'
            candidate.build(output)
            self.assertEqual((output / 'README.md').read_bytes(), (ROOT / 'README.md').read_bytes())
            self.assertEqual((output / 'THIRD_PARTY_NOTICES.md').read_bytes(), (ROOT / 'THIRD_PARTY_NOTICES.md').read_bytes())
            self.assertEqual((output / 'licenses/upstream/watch-MIT.txt').read_bytes(), (ROOT / 'licenses/upstream/watch-MIT.txt').read_bytes())
            self.assertIn('MIT License', (output / 'LICENSE').read_text(encoding='utf-8'))
            self.assertTrue((output / 'docs/reader-reference.md').is_file())
            self.assertTrue((output / 'reading_tasks/cli.py').is_file())
            self.assertTrue((output / 'scroll_agent/mcp_server.py').is_file())
            self.assertTrue((output / 'tools/build_dsh_index.py').is_file())
            self.assertTrue((output / 'tools/build_mcpb.py').is_file())
            for script in ('install_scroll_task.ps1', 'run_scroll_daily.ps1', 'manage_scroll_background.ps1',
                           'run_scroll_background.ps1', 'scheduled_task_action.ps1', 'run_scheduled_hidden.py'):
                self.assertEqual((output / 'tools' / script).read_bytes(), (ROOT / 'tools' / script).read_bytes())
            self.assertEqual(json.loads((output / 'adapters/mcpb/scroll/manifest.json').read_text())['name'], 'scroll-agent')
            self.assertEqual(json.loads((output / 'discovery/dsh/index.json').read_text(encoding='utf-8'))['format'], 1)
            bundle = json.loads((output / 'adapters/dsh/package.json').read_text(encoding='utf-8'))
            self.assertEqual(bundle['dsh']['bundle']['patch'], './cordis.patch.yml')
            self.assertTrue((output / 'adapters/dsh/cordis.patch.yml').is_file())
            self.assertEqual((output / 'adapters/dsh/LICENSE').read_bytes(), (ROOT / 'LICENSE').read_bytes())
            manifest = json.loads((output / 'candidate-manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['original_code_license'], 'MIT')
            forbidden = {'config.json', '.venv', 'data', 'auth', 'models', 'integrations', '.git'}
            self.assertFalse(any(p.name in forbidden for p in output.iterdir()))
            for name, sha in manifest['files'].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), sha)


if __name__ == '__main__':
    unittest.main()
