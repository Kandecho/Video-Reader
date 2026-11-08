from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock, patch

from PIL import Image

from test_agent import AgentFixture, URL
from scroll_agent import host as agent_host, mcp_server
from scroll_agent.agent import Agent
from scroll_agent.cli import configure, dispatch
from video_reader.cli import parser
from video_reader.common import ReaderError, read_json, write_json


class RuntimeTests(AgentFixture):
    def source_reader(self):
        self.reader.read = Mock(return_value={
            'title': 'Cached source', 'metadata': {'duration_seconds': 12},
            'visual': {'frames': [{'id': 'source_0', 'time': '00:01', 'path': 'unused.jpg'}]}})
        self.reader.transcript = Mock(return_value={
            'segments': [{'start': 0, 'end': 2, 'text': 'Actual cached speech'}],
            'source': 'captions', 'status': 'available', 'next_offset': 200})

    def test_cached_reader_contract_preserves_part_and_truncation(self):
        self.source_reader()
        url = URL.replace('p=1', 'p=2')
        write_json(self.reader.cache / 'v_fixture' / 'manifest.json', {
            'id': 'v_fixture', 'source': {'canonical': url},
            'authentication': {'account_marker': self.agent.scope}})
        material = self.agent._cached_material({'url': url})
        self.assertEqual(material['part'], 2)
        self.assertEqual(len(material['frames']), 1)
        self.assertIn('speech_page_truncated', material['gaps'])
        self.reader.transcript.assert_called_once_with('v_fixture', limit=200, transcribe=False, verify=False, _delivery=False)

    def test_deep_read_reuses_core_and_is_bounded(self):
        self.source_reader()
        self.reader.open = Mock(return_value={'session_id': 'v_fixture'})
        self.agent.options['deep_read']['max_videos'] = 1
        self.material['duration_seconds'] = 12
        second = {**self.material, 'url': URL.replace('p=1', 'p=2')}
        packet = {'previews': [self.material, second], 'failures': []}
        decisions = [{'url': item['url'], 'needs_deep_read': True} for item in packet['previews']]
        self.assertEqual(self.agent._deepen(packet, decisions), 1)
        self.reader.open.assert_called_once_with(URL)
        self.reader.transcript.assert_called_once_with('v_fixture', limit=200, transcribe=True, verify=False, _delivery=False)
        self.assertEqual(self.material['material_level'], 'source_frames_and_machine_speech')
        self.assertFalse(self.material['caption']['proofread'])

    def test_paused_or_over_budget_duration_never_starts_deep_read(self):
        self.reader.open = Mock()
        packet = {'previews': [self.material], 'failures': []}
        decisions = [{'url': URL, 'needs_deep_read': True}]
        self.material['duration_seconds'] = 9999
        self.assertEqual(self.agent._deepen(packet, decisions), 0)
        self.material['duration_seconds'] = 12
        self.platform.status.return_value = {'paused': 'http_429'}
        self.assertEqual(self.agent._deepen(packet, decisions), 0)
        self.reader.open.assert_not_called()

    def test_separate_delivery_updates_archive_and_duplicate_keeps_original(self):
        packet = self.prepare()
        self.agent.finish(packet['run_id'], self.decision())
        self.agent.options['delivery'].update(enabled=True, recipient_uid=999)
        self.agent.deliver(packet['run_id'])
        self.agent.deliver(packet['run_id'])
        saved = read_json(self.agent.directory(packet['run_id']) / 'result.json')
        self.assertEqual(saved['delivery']['message_key'], '654')
        self.assertEqual(self.platform.request.call_count, 1)

    def test_second_instance_cannot_start_overlapping_round(self):
        second = Agent(self.reader, platform=self.platform)
        with self.agent.lock, self.assertRaisesRegex(ReaderError, 'active'):
            second.prepare()

    def test_configuration_preserves_other_sections_and_rejects_bad_values(self):
        write_json(self.config_path, {'cache_dir': 'keep-cache', 'gemini': {'enabled': False},
                                     'agent': {'delivery': {'recipient_uid': 999}}})
        configure(self.config_path, {'preview_count': 4})
        saved = read_json(self.config_path)
        self.assertEqual(saved['cache_dir'], 'keep-cache')
        self.assertEqual(saved['agent']['delivery']['recipient_uid'], 999)
        for payload in ({'host': {'executable': False}}, {'deep_read': {'max_duration_seconds': True}},
                        {'wake': {'windows': None}}, {'unknown': 1}):
            with self.subTest(payload=payload), self.assertRaises(ReaderError):
                configure(self.config_path, payload)

    def test_disabled_watch_does_not_enter_polling(self):
        args = parser().parse_args(['--config', str(self.config_path), 'agent', 'watch', '--offline'])
        with patch('scroll_agent.cli.Agent', return_value=self.agent), \
                patch('scroll_agent.cli.time.sleep', side_effect=AssertionError('no watcher')):
            self.assertFalse(dispatch(self.reader, args)['watch_started'])


class ImageContractTests(AgentFixture):
    def image(self):
        path = self.root / 'frame.jpg'
        Image.new('RGB', (32, 32), 'red').save(path)
        return {'id': 'preview_0', 'time': 1, 'path': str(path)}

    def test_preview_pack_contains_native_image_not_just_path(self):
        blocks = mcp_server.pack({'frames': [self.image()]})
        self.assertEqual(sum(block.type == 'image' for block in blocks), 1)

    def test_host_prepare_images_identify_the_source_video(self):
        self.material['frames'] = [self.image()]
        packet = {'previews': [self.material]}
        with patch('scroll_agent.mcp_server.Agent', return_value=self.agent), \
                patch.object(self.agent, 'prepare', return_value=packet):
            blocks = mcp_server.scroll_round(action='prepare')
        self.assertEqual(sum(block.type == 'image' for block in blocks), 1)
        self.assertIn(URL, blocks[1].text)


class HostTests(AgentFixture):
    def test_explicit_host_path_is_preserved(self):
        executable = Path(subprocess.__file__)
        with patch('scroll_agent.host.shutil.which') as search:
            self.assertEqual(agent_host.resolve_executable({'executable': str(executable)}), str(executable.resolve()))
        search.assert_not_called()

    def test_missing_explicit_host_does_not_silently_change_runtime(self):
        with patch('scroll_agent.host.shutil.which', return_value=None), \
                self.assertRaisesRegex(ReaderError, 'Configured Codex CLI not found'):
            agent_host.resolve_executable({'executable': str(self.root / 'removed' / 'codex.exe')})

    def test_automatic_host_uses_path(self):
        with patch('scroll_agent.host.shutil.which', return_value='path/codex.exe'):
            self.assertEqual(agent_host.resolve_executable({}), 'path/codex.exe')

    def test_windows_app_host_is_discovered_without_path(self):
        if os.name != 'nt':
            self.skipTest('Windows bundled CLI discovery')
        directory = self.root / 'AppData' / 'Local' / 'OpenAI' / 'Codex' / 'bin'
        older = directory / 'old' / 'codex.exe'
        newer = directory / 'new' / 'codex.exe'
        older.parent.mkdir(parents=True)
        newer.parent.mkdir(parents=True)
        older.touch()
        newer.touch()
        os.utime(older, (1000, 1000))
        os.utime(newer, (2000, 2000))
        with patch('scroll_agent.host.shutil.which', return_value=None), \
                patch('scroll_agent.host.Path.home', return_value=self.root):
            self.assertEqual(agent_host.resolve_executable({}), str(newer))
            newer.unlink()
            replacement = directory / 'updated' / 'codex.exe'
            replacement.parent.mkdir()
            replacement.touch()
            self.assertEqual(agent_host.resolve_executable({}), str(replacement))

    def test_missing_automatic_host_reports_dependency(self):
        with patch('scroll_agent.host.shutil.which', return_value=None), \
                patch('scroll_agent.host.Path.home', return_value=self.root), \
                self.assertRaisesRegex(ReaderError, 'Codex CLI not found'):
            agent_host.resolve_executable({})

    def test_ephemeral_host_gets_images_and_schema_without_a_shell(self):
        directory = self.root / 'round'
        directory.mkdir()
        packet = {'previews': [{'frames': [{'path': 'one.jpg'}]}]}
        process = Mock(returncode=0)
        process.communicate.side_effect = lambda *args, **kwargs: write_json(
            directory / 'host' / 'decision.json', {'decisions': []})
        options = {**self.agent.options['host'], 'executable': str(Path(subprocess.__file__))}
        with patch('scroll_agent.host.subprocess.Popen', return_value=process) as spawn, \
                patch('video_reader.processes.identity', return_value=None), \
                patch('scroll_agent.host.model_options', return_value=[]):
            self.assertEqual(agent_host.decide(packet, directory, options), {'decisions': []})
        command = spawn.call_args.args[0]
        for flag in ('--ephemeral', '--ignore-user-config', '--output-schema', '--image', '--json'):
            self.assertIn(flag, command)
        self.assertIn('features.shell_tool=false', command)
        self.assertFalse(spawn.call_args.kwargs.get('shell', False))

    def test_old_host_output_is_not_accepted_as_a_new_decision(self):
        directory = self.root / 'round'
        write_json(directory / 'host' / 'decision.json', {'decisions': []})
        options = {**self.agent.options['host'], 'executable': str(Path(subprocess.__file__))}
        with patch('scroll_agent.host.subprocess.Popen', return_value=Mock(returncode=0)), \
                patch('video_reader.processes.identity', return_value=None), \
                patch('scroll_agent.host.model_options', return_value=[]), \
                self.assertRaisesRegex(ReaderError, 'failed'):
            agent_host.decide({'previews': []}, directory, options)

    def test_timeout_stops_only_the_spawned_host(self):
        directory = self.root / 'round'
        directory.mkdir()
        process = Mock(pid=424242)
        process.communicate.side_effect = subprocess.TimeoutExpired('codex', 1)
        options = {**self.agent.options['host'], 'executable': str(Path(subprocess.__file__))}
        with patch('scroll_agent.host.subprocess.Popen', return_value=process), \
                patch('scroll_agent.host.subprocess.run') as terminate, \
                patch('scroll_agent.host.model_options', return_value=[]), \
                self.assertRaisesRegex(ReaderError, 'timed out'):
            agent_host.decide({'previews': []}, directory, options)
        if agent_host.os.name == 'nt':
            self.assertEqual(terminate.call_args.args[0], ['taskkill', '/PID', '424242', '/T', '/F'])
        else:
            process.kill.assert_called_once()
