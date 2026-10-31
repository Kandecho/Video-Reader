"""Regression: isolated Python entry points must not poison UTF-8 MCP logging."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class StdioEncodingTests(unittest.TestCase):
    def run_entry(self, body, input_text=''):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            config.write_text(json.dumps({'cache_dir': str(Path(directory) / 'cache'),
                                          'vision': {'enabled': False}}), encoding='utf-8')
            env = dict(os.environ, VIDEO_READER_CONFIG=str(config), PYTHONIOENCODING='ascii')
            code = f'import sys; sys.path.insert(0, {str(ROOT)!r})\n' + body
            return subprocess.run([sys.executable, '-I', '-X', 'utf8=0', '-c', code],
                                  input=input_text.encode('utf-8'), stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, env=env, timeout=30)

    def test_standard_streams_round_trip_utf8_despite_legacy_encoding(self):
        result = self.run_entry('''
from video_reader.vendor.runtime import configure_stdio
for stream in (sys.stdin, sys.stdout, sys.stderr):
    stream.reconfigure(encoding='ascii')
configure_stdio()
text = sys.stdin.read()
print(text, end='')
print(text, file=sys.stderr, end='')
''', '中文进度 00:00–02:00 ✓')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.decode('utf-8'), '中文进度 00:00–02:00 ✓')
        self.assertEqual(result.stderr.decode('utf-8'), '中文进度 00:00–02:00 ✓')

    def check_mcp_entry(self, module):
        result = self.run_entry(f'''
import {module} as server
from video_reader.reader import print_progress
for stream in (sys.stdin, sys.stdout, sys.stderr):
    stream.reconfigure(encoding='ascii')
def run(**kwargs):
    assert kwargs['transport'] == 'stdio'
    assert all(s.encoding.lower().replace('_', '-') == 'utf-8'
               for s in (sys.stdin, sys.stdout, sys.stderr))
    print_progress('Transcribing source interval 00:00.000–02:00.000 using local model')
    print_progress('Preparing video source')
    print('完成')
server.mcp.run = run
server.main()
''')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(result.stdout.decode('utf-8').strip(), '完成')
        self.assertIn('00:00.000–02:00.000', result.stderr.decode('utf-8'))
        self.assertIn('Preparing video source', result.stderr.decode('utf-8'))

    def test_reader_mcp_configures_streams_before_transport(self):
        self.check_mcp_entry('video_reader.mcp_server')

    def test_scroll_mcp_configures_streams_before_transport(self):
        self.check_mcp_entry('scroll_agent.mcp_server')

    def check_cli_entry(self, module, command):
        result = self.run_entry(f'''
import {module} as cli
for stream in (sys.stdin, sys.stdout, sys.stderr):
    stream.reconfigure(encoding='ascii')
sys.argv = ['probe', {command!r}, '--未知参数']
cli.main()
''')
        self.assertEqual(result.returncode, 2)
        self.assertIn('--未知参数', result.stderr.decode('utf-8'))

    def test_reader_cli_error_is_utf8(self):
        self.check_cli_entry('video_reader.cli', 'doctor')

    def test_scroll_cli_error_is_utf8(self):
        self.check_cli_entry('scroll_agent.cli', 'status')

    def test_detached_worker_configures_utf8_before_progress(self):
        result = self.run_entry(f'''
import os, runpy
from types import SimpleNamespace
from video_reader import jobs
from video_reader.reader import print_progress
for stream in (sys.stdin, sys.stdout, sys.stderr):
    stream.reconfigure(encoding='ascii')
def execute():
    print_progress('中文进度 00:00–02:00')
    print('完成')
jobs.Running = lambda *args: SimpleNamespace(run=execute)
sys.argv = ['worker', os.environ['VIDEO_READER_CONFIG'],
            str(__import__('pathlib').Path(os.environ['VIDEO_READER_CONFIG']).parent/'cache/_jobs'), 'j_'+'a'*24]
runpy.run_path({str(ROOT/'video_reader/job_worker.py')!r}, run_name='__main__')
''')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(result.stdout.decode('utf-8').strip(), '完成')
        self.assertIn('中文进度 00:00–02:00', result.stderr.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
