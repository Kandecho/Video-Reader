"""Regression checks for frozen-audit fixes; synthetic assets, no network/models."""
import copy
import hashlib
import inspect
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from video_reader import delivery
from video_reader.common import ReaderError, read_json, write_json
from video_reader.jobs import CURRENT, Jobs, Running
from video_reader.mcp_content import pack
from video_reader.reader import Reader


ROOT = Path(__file__).resolve().parents[1]


class AuditFixTests(unittest.TestCase):
    def setUp(self):
        directory = ROOT / '.test-work'
        directory.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='architecture-fix-', dir=directory)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / 'config.json'
        write_json(self.config, {'cache_dir': 'cache', 'asr': {'model_path': None},
                                 'vision': {'enabled': False}, 'bilibili_auth': {'enabled': False}})
        self.reader = Reader(self.config)
        self.jobs = Jobs(self.reader)

    def start_job(self):
        process = Mock()
        process.wait.return_value = 0
        with patch('video_reader.jobs.subprocess.Popen', return_value=process):
            state = self.jobs.start('content', {'target': 'fixture'}, 0)
        return state['job_id']

    def test_worker_rejects_changed_effective_config_before_operation(self):
        job_id = self.start_job()
        self.reader.config['frame_width'] += 1
        with patch.object(self.reader, 'content') as operation:
            Running(self.jobs, job_id).run()
        operation.assert_not_called()
        state = self.jobs.status(job_id)
        self.assertEqual(state['status'], 'failed')
        self.assertIn('configuration/account changed', state['error']['message'])
        self.assertFalse((self.jobs.root / (job_id + '.result.json')).exists())

    def test_worker_runs_matching_config_and_preserves_result(self):
        job_id = self.start_job()
        with patch.object(self.reader, 'content', return_value={'marker': 'same-config'}) as operation:
            Running(self.jobs, job_id).run()
        operation.assert_called_once()
        result = self.jobs.result(job_id)
        self.assertEqual(result['job']['status'], 'completed')
        self.assertEqual(result['marker'], 'same-config')

    def test_worker_rejects_account_change_without_login_or_refresh(self):
        from video_reader.bilibili_auth import BilibiliAuth
        with patch.object(BilibiliAuth, 'account_scope', return_value='account-A'):
            job_id = self.start_job()
        with patch.object(BilibiliAuth, 'account_scope', return_value='account-B'), \
             patch.object(self.reader, 'content') as operation:
            Running(self.jobs, job_id).run()
        operation.assert_not_called()
        self.assertEqual(self.jobs.status(job_id)['status'], 'failed')

    def test_active_jobs_include_older_job_outside_display_limit_and_exclude_current(self):
        now = time.time()
        for number in range(25):
            job_id = 'j_' + f'{number:024x}'
            state = {'job_id': job_id, 'status': 'completed', 'stage': 'completed', 'created_at': now,
                     'heartbeat_at': now, 'progress_at': now, 'stage_started_at': now, 'finished_at': now}
            self.jobs.write_state(job_id, state)
        active_id = 'j_' + 'f'*24
        self.jobs.write_state(active_id, {'job_id': active_id, 'status': 'queued', 'stage': 'starting_worker',
                             'created_at': now, 'heartbeat_at': now, 'progress_at': now, 'stage_started_at': now})
        os.utime(self.jobs.path(active_id), (now-100, now-100))
        self.assertNotIn(active_id, [state['job_id'] for state in self.jobs.list()['jobs']])
        self.assertEqual([state['job_id'] for state in self.reader.active_jobs()], [active_id])
        self.assertEqual(self.reader.active_jobs(exclude=[active_id]), [])
        token = CURRENT.set(Mock(job_id=active_id))
        try:
            self.assertEqual(self.reader.active_jobs(), [])
        finally:
            CURRENT.reset(token)

    def material(self):
        frames = []
        for index in range(2):
            path = self.root / f'frame-{index}.jpg'
            Image.new('RGB', (32, 32), ('blue', 'red')[index]).save(path)
            frames.append({'id': f'frame-{index}', 'path': str(path), 'time': str(index),
                           'timestamp_seconds': index, 'ocr': {'raw': 'original'*2000}})
        return {'visual': {'frames': frames}, 'speech': {'segments': []}, 'evidence': 'x'*30000}

    def test_reading_pages_attach_pixels_once_and_retain_every_evidence_field(self):
        result = self.material()
        pages = delivery.pages(copy.deepcopy(result), 10000, 1024*1024, reading=True)
        self.assertEqual(sum(block.type == 'image' for page in pages for block in pack(page)), 2)
        restored = delivery.restore([part for page in pages for part in page.get('material_parts', [])])
        self.assertEqual(restored, result)
        self.assertEqual([frame['id'] for page in pages for frame in page.get('visual', {}).get('frames', [])],
                         ['frame-0', 'frame-1'])
        # A new request or an explicit evidence view may attach the images again.
        for reading in (True, False):
            repeated = delivery.pages(copy.deepcopy(result), 10000, 1024*1024, reading=reading)
            self.assertEqual(sum(block.type == 'image' for page in repeated for block in pack(page)), 2)

    def test_partial_projection_keeps_remaining_images_and_stability_reference(self):
        result = self.material()
        reference = self.root / 'reference.jpg'
        Image.new('RGB', (32, 32), 'green').save(reference)
        result['visual']['frames'][0]['temporal'] = {'stable_reference': {'path': str(reference), 'time': '0.1'}}
        budget = Path(result['visual']['frames'][0]['path']).stat().st_size
        pages = delivery.pages(result, 10000, budget, reading=True)
        self.assertEqual(len(pages[0]['visual']['frames']), 1)
        self.assertEqual(sum(block.type == 'image' for page in pages for block in pack(page)), 3)

    def test_reader_owns_evidence_binding_hash_and_asset_validation(self):
        frame = self.material()['visual']['frames'][0]
        data = {'platform_metadata': {'cid': 7}, 'authentication': {'account_marker': 'account'}}
        request = [{'start': 0, 'end': 1}]
        with patch.object(self.reader, 'load', return_value=data), \
             patch.object(self.reader, 'read', return_value={'visual': {'frames': [frame]}}) as read:
            with self.assertRaisesRegex(ReaderError, 'CID'):
                self.reader.evidence_frames('fixture', request, {'cid': 8})
            with self.assertRaisesRegex(ReaderError, 'account'):
                self.reader.evidence_frames('fixture', request, {'cid': 7, 'account_scope': 'other'})
            read.assert_not_called()
            frames = self.reader.evidence_frames('fixture', request, {'cid': 7, 'account_scope': 'account'})
        self.assertEqual(frames[0]['asset_sha256'], hashlib.sha256(Path(frame['path']).read_bytes()).hexdigest())
        self.reader.validate_assets(frames)
        Path(frame['path']).write_bytes(b'changed pixels')
        with self.assertRaisesRegex(ReaderError, 'changed'):
            self.reader.validate_assets(frames)

    def test_entrypoints_keep_saved_profile_selection(self):
        from video_reader import cli, mcp_server
        for command in ('read', 'transcript'):
            args = cli.parser().parse_args([command, 'fixture', '--speech-profile', 'old-track'])
            self.assertEqual(args.speech_profile, 'old-track')
        args = cli.parser().parse_args(['review', 'prepare', 'fixture', '--speech-profile', 'old-track'])
        self.assertEqual(args.speech_profile, 'old-track')
        args = cli.parser().parse_args(['export', 'fixture', str(self.root/'export'), '--revision', '1',
                                      '--speech-profile', 'old-track'])
        self.assertEqual(args.speech_profile, 'old-track')
        for function in (mcp_server.video_read, mcp_server.video_transcript, mcp_server.video_review, mcp_server.video_export):
            self.assertIn('speech_profile', inspect.signature(function).parameters)
        with patch.object(mcp_server.reader, 'job', return_value={}) as invoke:
            mcp_server.video_read('fixture', speech_profile='old-track')
            self.assertEqual(invoke.call_args.kwargs['parameters']['speech_profile'], 'old-track')
            mcp_server.video_transcript('fixture', speech_profile='old-track')
            self.assertEqual(invoke.call_args.kwargs['parameters']['speech_profile'], 'old-track')


if __name__ == '__main__':
    unittest.main()
