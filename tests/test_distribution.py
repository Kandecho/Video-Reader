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
            manifest = json.loads((output / 'candidate-manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['original_code_license'], 'MIT')
            forbidden = {'config.json', '.venv', 'data', 'auth', 'models', 'integrations', '.git'}
            self.assertFalse(any(p.name in forbidden for p in output.iterdir()))
            for name, sha in manifest['files'].items():
                self.assertEqual(hashlib.sha256((output / name).read_bytes()).hexdigest(), sha)


if __name__ == '__main__':
    unittest.main()
