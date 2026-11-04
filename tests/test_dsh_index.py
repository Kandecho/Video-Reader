import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('dsh_index', Path(__file__).resolve().parents[1] / 'tools/build_dsh_index.py')
index = importlib.util.module_from_spec(spec)
spec.loader.exec_module(index)


class DshIndexTests(unittest.TestCase):
    def test_release_metadata_and_install_target_do_not_follow_working_tree(self):
        commit = 'a' * 40
        manifest = {'name': 'dsh-video-reader', 'version': '0.1.0', 'author': 'author',
                    'homepage': 'https://example.org', 'dsh': {'bundle': {'patch': './cordis.patch.yml'}},
                    'engines': {'dsh': '>=0.2.2-rc.1'}, 'keywords': ['video'], 'os': ['win32']}
        locale = {'meta': {'title': 'Released title', 'description': 'Released description'}}
        def git(command, cwd):
            if command == ['git', 'show', '-s', '--format=%ct', commit]:
                return b'1793797035\n'
            self.assertEqual(command[:2], ['git', 'show'])
            self.assertTrue(command[2].startswith(commit + ':adapters/dsh/'))
            return json.dumps(manifest if command[2].endswith('package.json') else locale).encode()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'adapters/dsh').mkdir(parents=True)
            (root / 'adapters/dsh/package.json').write_text('{"version":"9.9.9"}', encoding='utf-8')
            with patch.object(index.subprocess, 'check_output', side_effect=git):
                result = index.build(commit, root)
        plugin = result['plugins'][0]
        self.assertEqual(plugin['versions'][0]['version'], '0.1.0')
        self.assertEqual(plugin['versions'][0]['source'],
                         {'type': 'git', 'url': index.REPOSITORY, 'commit': commit, 'path': 'adapters/dsh'})
        self.assertEqual(plugin['title']['en'], 'Released title')
        self.assertTrue(plugin['description']['en'].startswith('Windows.'))

    def test_floating_or_short_refs_are_rejected_before_reading_git(self):
        for value in ['main', 'f2656bf', '--help']:
            with self.subTest(value=value), patch.object(index.subprocess, 'check_output') as git:
                with self.assertRaisesRegex(ValueError, 'full immutable'):
                    index.build(value)
                git.assert_not_called()

    def test_private_or_non_bundle_release_is_not_published(self):
        for manifest in [{'private': True, 'version': '0.1.0'}, {'version': '0.1.0'}]:
            with self.subTest(manifest=manifest), patch.object(index.subprocess, 'check_output', return_value=json.dumps(manifest).encode()):
                with self.assertRaisesRegex(ValueError, 'public DSH bundle'):
                    index.build('a' * 40)


if __name__ == '__main__':
    unittest.main()
