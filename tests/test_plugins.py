import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / 'tools/build_plugins.py'
SPEC = importlib.util.spec_from_file_location('build_plugins', MODULE_PATH)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / 'Shared Core with spaces'
        for relative in ('.venv/Scripts/python.exe', 'launch_mcp.py', 'launch_scroll.py', 'run.ps1', 'config.json'):
            builder.write(self.root / relative, 'fixture')
        builder.write(self.root / 'skill/SKILL.md', '---\nname: video-read\ndescription: Read videos.\n---\n\n'
                      + builder.CORE_NOTICE + '\n\nKeep original evidence.\n')
        self.before = (self.root / 'config.json').read_bytes()
        builder.write(self.root / 'scroll-skill/SKILL.md', builder.SCROLL_NOTICE)
        self.summary = builder.build(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_both_adapters_launch_same_external_core_and_configuration(self):
        for host in self.summary['hosts'].values():
            server = json.loads((Path(host['plugin_root']) / '.mcp.json').read_text())['mcpServers']['video-reader']
            self.assertEqual(server['command'], str(self.root / '.venv/Scripts/python.exe'))
            self.assertEqual(server['args'], ['-I', str(self.root / 'launch_mcp.py')])
            self.assertEqual(server['env']['VIDEO_READER_CONFIG'], str(self.root / 'config.json'))
        self.assertEqual((self.root / 'config.json').read_bytes(), self.before)

    def test_only_thin_files_are_packaged(self):
        for host in self.summary['hosts'].values():
            files = list(Path(host['plugin_root']).rglob('*'))
            self.assertEqual(len([path for path in files if path.is_file()]), 5)
            self.assertFalse(any(path.name in ('auth', 'models', 'data', '.venv') or path.is_symlink() for path in files))

    def test_skills_share_source_but_do_not_infer_core_from_plugin_cache(self):
        skills = [(Path(host['plugin_root']) / 'skills/video-read/SKILL.md').read_text()
                  for host in self.summary['hosts'].values()]
        self.assertEqual(skills[0], skills[1])
        self.assertIn(self.root.as_posix(), skills[0])
        self.assertNotIn(builder.CORE_NOTICE, skills[0])
        self.assertIn('Keep original evidence.', skills[0])

    def test_rebuild_is_idempotent_and_preserves_canonical_source(self):
        original = (self.root / 'skill/SKILL.md').read_bytes()
        self.assertEqual(builder.build(self.root), self.summary)
        self.assertEqual((self.root / 'skill/SKILL.md').read_bytes(), original)

    def test_catalog_paths_resolve_to_packages_without_parent_traversal(self):
        for name, host in self.summary['hosts'].items():
            catalog = Path(host['catalog'])
            entry = json.loads(catalog.read_text())['plugins'][0]
            relative = entry['source']['path'] if name == 'codex' else entry['source']
            base = Path(host['marketplace_root'])
            self.assertEqual((base / relative).resolve(), Path(host['plugin_root']))
            self.assertNotIn('..', Path(relative).parts)

    def test_missing_core_or_changed_skill_location_fails_without_copying_runtime(self):
        (self.root / 'launch_mcp.py').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing shared core'):
            builder.build(self.root)
        builder.write(self.root / 'launch_mcp.py', 'fixture')
        builder.write(self.root / 'skill/SKILL.md', 'changed')
        with self.assertRaisesRegex(ValueError, 'core-location paragraph changed'):
            builder.build(self.root)

    def test_host_timeouts_use_correct_units(self):
        for name, host in self.summary['hosts'].items():
            server = json.loads((Path(host['plugin_root']) / '.mcp.json').read_text())['mcpServers']['video-reader']
            key, expected = ('tool_timeout_sec', 3600) if name == 'codex' else ('timeout', 3600000)
            self.assertEqual(server[key], expected)


if __name__ == '__main__':
    unittest.main()
