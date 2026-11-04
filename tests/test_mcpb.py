"""Thin bundle contents and core/configuration routing; no accounts or models."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mcpb_builder', ROOT / 'tools/build_mcpb.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class McpbTests(unittest.TestCase):
    def test_only_public_adapter_files_and_repeatable_archives(self):
        with tempfile.TemporaryDirectory() as temp:
            first = builder.build(Path(temp) / 'first')
            second = builder.build(Path(temp) / 'second')
            self.assertEqual(first, second)
            self.assertEqual({a['service'] for a in first}, {'reader', 'scroll'})
            for item in first:
                registration = json.loads((ROOT / 'discovery/mcp' / f'{item["service"]}.server.json').read_text(encoding='utf-8'))
                self.assertEqual(registration['packages'][0]['fileSha256'], item['sha256'])
                self.assertTrue(registration['packages'][0]['identifier'].endswith('/' + item['filename']))
                with zipfile.ZipFile(Path(temp) / 'first' / item['filename']) as bundle:
                    self.assertEqual(set(bundle.namelist()), {'manifest.json', 'server/launch.py', 'LICENSE', 'README.md'})
                    manifest = json.loads(bundle.read('manifest.json'))
                    self.assertTrue(manifest['user_config']['core_root']['required'])
                    self.assertEqual(manifest['compatibility']['platforms'], ['win32'])
                    self.assertEqual(manifest['server']['mcp_config']['args'][-1], item['service'])
            with self.assertRaises(ValueError):
                builder.build(Path(temp) / 'first')

    def test_launcher_routes_both_services_and_config_from_unrelated_cwd(self):
        with tempfile.TemporaryDirectory(prefix='mcpb-') as temp:
            core = Path(temp) / '核心 with spaces'
            core.mkdir()
            config = core / 'config.json'
            config.write_text('{}', encoding='utf-8')
            alternate = Path(temp) / '另一份 config.json'
            alternate.write_text('{}', encoding='utf-8')
            fake = ('import json, os, sys\nprint(json.dumps({"argv":sys.argv[1:],'
                    '"cwd":os.getcwd(),"config":os.environ["VIDEO_READER_CONFIG"]}))\n')
            for entry in ('launch_mcp.py', 'launch_scroll.py'):
                (core / entry).write_text(fake, encoding='utf-8')
            for service, override in [('reader', ''), ('scroll', str(alternate))]:
                result = subprocess.run([sys.executable, '-I', str(ROOT / 'adapters/mcpb/launch.py'), service],
                    cwd=temp, env={**os.environ, 'VIDEO_READER_ROOT': str(core), 'VIDEO_READER_CONFIG': override},
                    capture_output=True, text=True, encoding='utf-8', timeout=15, check=True)
                actual = json.loads(result.stdout)
                self.assertEqual(Path(actual['cwd']), core)
                self.assertEqual(Path(actual['config']), alternate if override else config)
                self.assertEqual(actual['argv'], ['--mcp'] if service == 'scroll' else [])

    def test_missing_core_gives_setup_error_without_protocol_stdout(self):
        result = subprocess.run([sys.executable, '-I', str(ROOT / 'adapters/mcpb/launch.py'), 'reader'],
            env={**os.environ, 'VIDEO_READER_ROOT': ''}, capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertIn('Select your prepared Video Reader installation', result.stderr)


if __name__ == '__main__':
    unittest.main()
