"""Interactive visual observations retain provenance without replaying source pixels."""
import copy
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from reading_tasks.visual import Visual
from video_reader.common import ReaderError, read_json, write_json
from video_reader.mcp_content import pack
from video_reader.reader import Reader


class VisualObserveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = self.root / 'config.json'
        write_json(config, {'cache_dir': 'cache', 'tasks': {'directory': 'tasks'},
                            'agent': {'directory': 'agent'}})
        self.reader = Reader(config)
        self.session = 'v_' + 'a' * 24
        self.index_id = 'ci_' + 'b' * 24
        self.binding = {
            'session_id': self.session,
            'source': 'https://www.bilibili.com/video/BV0000000001?p=2',
            'account_scope': 'fixture-account', 'speech_source': 'auto', 'context': '',
            'speech_material': 'speech-original', 'review_snapshot': 'review-original',
            'review_revision': 1, 'media_identity': {'size': 123, 'mtime_ns': 456},
            'coverage': {'complete': True},
        }
        self.reader.content = Mock(side_effect=lambda *args, **kwargs: {
            'index_id': self.index_id, 'valid': True, 'binding': copy.deepcopy(self.binding)})
        self.reader.load = Mock(return_value={'metadata': {'duration_seconds': 816}})
        self.reader.source_frames = Mock(side_effect=self.source_frames)
        self.reader.job = Mock(return_value={'job_id': 'j_' + 'c' * 24, 'status': 'queued'})
        self.visual = Visual(self.reader)
        self.calls = []

    def source_frames(self, session, requests):
        self.assertEqual(session, self.session)
        frames = []
        for request in requests:
            time = request['timestamp_seconds']
            path = self.root / f'frame-{time}.jpg'
            Image.new('RGB', (320, 180), (int(time) % 256, 15, 40)).save(path)
            frames.append({'id': f'frame:{time}', 'path': str(path), 'time': str(time),
                           'timestamp_seconds': time, 'precision': 'source_frame',
                           'region': request.get('region'),
                           'asset_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        return {'session_id': session, 'frames': frames}

    def response(self, prompt, images, schema, directory, options, **kwargs):
        packet = json.loads(prompt.split('\n', 1)[1])['material']
        self.calls.append({'packet': copy.deepcopy(packet), 'images': list(images),
                           'directory': Path(directory)})
        frame_ids = [frame['id'] for frame in packet['frames']]
        return {'packet_id': packet['packet_id'], 'observed_frame_ids': frame_ids,
                'records': [{'kind': 'screen_text', 'text': 'PaymentResult pay(PaymentCommand cmd);',
                             'frame_ids': frame_ids}],
                'uncertainties': [], 'task_satisfied': True}

    def execute(self, timestamp=397, **options):
        return self.visual.execute(self.session, self.index_id, '逐字记录画面里的方法签名',
                                   [{'timestamp_seconds': timestamp}], **options)

    def accepted_records(self):
        records = []
        for path in self.root.rglob('*.json'):
            value = read_json(path)
            if (isinstance(value, dict) and value.get('observation_id', '').startswith('vo_')
                    and 'evidence_records' in value):
                records.append(value)
        return records

    def test_start_uses_shared_job_without_observing_or_completing_a_queue_item(self):
        result = self.visual.start(self.session, self.index_id, '读画面代码',
                                   [{'timestamp_seconds': 397}], wait_seconds=0)
        self.assertEqual(result['job_id'], 'j_' + 'c' * 24)
        self.reader.source_frames.assert_not_called()
        self.reader.job.assert_called_once()
        self.assertEqual(self.reader.job.call_args.args, ('start',))
        self.assertEqual(self.reader.job.call_args.kwargs['operation'], 'observe_visual')
        self.assertEqual(self.reader.job.call_args.kwargs['wait_seconds'], 0)
        parameters = self.reader.job.call_args.kwargs['parameters']
        self.assertEqual(parameters['session'], self.session)
        self.assertEqual(parameters['index_id'], self.index_id)
        self.assertNotIn('wait_seconds', parameters)
        self.assertFalse(any(self.root.rglob('result.md')))

    def test_two_independent_observations_only_attach_current_pixels_and_pass_prior_text(self):
        with patch('reading_tasks.visual.invoke', side_effect=self.response) as host:
            first = self.execute(397)
            second = self.execute(464, prior_observation_ids=[first['observation_id']])
        self.assertEqual(host.call_count, 2)
        self.assertNotEqual(first['observation_id'], second['observation_id'])
        self.assertNotEqual(self.calls[0]['directory'], self.calls[1]['directory'])
        self.assertEqual(len(self.calls[1]['images']), 1)
        self.assertNotEqual(self.calls[0]['images'], self.calls[1]['images'])
        second_packet = self.calls[1]['packet']
        self.assertEqual([f['id'] for f in second_packet['frames']], ['frame:464'])
        prior = json.dumps(second_packet['prior_observations'], ensure_ascii=False)
        self.assertIn('PaymentResult pay(PaymentCommand cmd);', prior)
        self.assertIn(first['observation_id'], prior)
        self.assertNotIn('path', prior)
        self.assertNotIn(self.calls[0]['images'][0], prior)
        self.assertEqual(second['prior_observation_ids'], [first['observation_id']])

    def test_return_and_saved_record_are_text_only_with_source_revision_and_pixel_identity(self):
        with patch('reading_tasks.visual.invoke', side_effect=self.response):
            result = self.execute()
        self.assertRegex(result['observation_id'], r'^vo_[a-f0-9]{32}$')
        self.assertEqual(result['binding'], self.binding)
        self.assertEqual(result['index_id'], self.index_id)
        self.assertTrue(result['observer'])
        frame = result['image_refs'][0]
        self.assertEqual(frame['id'], 'frame:397')
        self.assertEqual(frame['timestamp_seconds'], 397)
        self.assertEqual((frame['width'], frame['height']), (320, 180))
        self.assertEqual(frame['sha256'], hashlib.sha256(Path(self.calls[0]['images'][0]).read_bytes()).hexdigest())
        self.assertIsNone(frame['region'])
        self.assertNotIn('path', frame)
        self.assertEqual(result['evidence_records'][0]['frame_ids'], ['frame:397'])
        self.assertEqual(result['evidence_records'][0]['kind'], 'screen_text')
        self.assertIn('id', result['evidence_records'][0])
        self.assertIn('metrics', result)
        self.assertNotIn('frames', result)
        self.assertNotIn('visual', result)
        self.assertFalse(any(item.type == 'image' for item in pack(result)))
        shown = self.visual.show(result['observation_id'])
        self.assertTrue(shown['current_material_valid'])
        self.assertEqual(shown['evidence_records'], result['evidence_records'])
        self.assertFalse(any(item.type == 'image' for item in pack(shown)))

    def test_unresolved_visual_question_retains_unknown_and_does_not_require_false_success(self):
        def uncertain(*args, **kwargs):
            result = self.response(*args, **kwargs)
            result.update(task_satisfied=False, uncertainties=['这一帧未显示 authorize 的定义'])
            result['records'][0]['kind'] = 'visual_observation'
            result['records'][0]['text'] = '当前仅见 pay 方法签名'
            return result
        with patch('reading_tasks.visual.invoke', side_effect=uncertain):
            result = self.execute()
        self.assertFalse(result['task_satisfied'])
        self.assertEqual(result['uncertainties'], ['这一帧未显示 authorize 的定义'])
        self.assertFalse(self.visual.show(result['observation_id'])['task_satisfied'])

    def test_crop_revisit_returns_exact_observed_pixels_instead_of_reextracting_source(self):
        region = [.25, .1, .75, .9]
        with patch('reading_tasks.visual.invoke', side_effect=self.response):
            result = self.visual.execute(self.session, self.index_id, '抄录局部代码',
                [{'timestamp_seconds': 397, 'width': 3840, 'region': region}])
        frame = result['image_refs'][0]
        self.assertEqual(frame['region'], region)
        self.assertEqual(frame['revisit'], {'action': 'visual-frame', 'item_id': result['observation_id'],
                                           'parameters': {'index': 0}})
        revisited = self.visual.revisit(result['observation_id'], index=0)
        self.reader.source_frames.assert_called_once()
        self.assertEqual(revisited['observation_id'], result['observation_id'])
        self.assertEqual(revisited['binding'], self.binding)
        asset = revisited['visual']['frames'][0]
        self.assertEqual(asset['region'], region)
        self.assertEqual(hashlib.sha256(Path(asset['path']).read_bytes()).hexdigest(), frame['sha256'])
        images = [item for item in pack(revisited) if item.type == 'image']
        self.assertEqual(len(images), 1)
        self.assertEqual(hashlib.sha256(base64.b64decode(images[0].data)).hexdigest(), frame['sha256'])

    def test_host_cannot_claim_a_prior_or_unattached_frame_as_current_evidence(self):
        def forged(*args, **kwargs):
            result = self.response(*args, **kwargs)
            result['records'][0]['frame_ids'] = ['frame:not-delivered']
            return result
        with patch('reading_tasks.visual.invoke', side_effect=forged):
            with self.assertRaises(ReaderError):
                self.execute()
        self.assertFalse(self.accepted_records())

    def test_accepted_observation_must_cover_exactly_the_current_attachment_ids(self):
        for observed in ([], ['frame:397', 'frame:not-delivered']):
            def wrong_observation(*args, **kwargs):
                response = self.response(*args, **kwargs)
                response['observed_frame_ids'] = observed
                return response
            with self.subTest(observed=observed), patch('reading_tasks.visual.invoke', side_effect=wrong_observation):
                with self.assertRaises(ReaderError):
                    self.execute()

    def test_empty_or_unreferenced_records_cannot_be_saved_as_observations(self):
        for records in ([], [{'kind': 'screen_text', 'text': 'guess', 'frame_ids': []}]):
            def empty_evidence(*args, **kwargs):
                result = self.response(*args, **kwargs)
                result['records'] = records
                return result
            with self.subTest(records=records), patch('reading_tasks.visual.invoke', side_effect=empty_evidence):
                with self.assertRaises(ReaderError):
                    self.execute()

    def test_failed_host_leaves_no_successful_observation_to_reuse(self):
        with patch('reading_tasks.visual.invoke', side_effect=ReaderError('host unavailable')):
            with self.assertRaisesRegex(ReaderError, 'host unavailable'):
                self.execute()
        self.assertFalse(self.accepted_records())

    def test_wrong_session_and_changed_revision_are_rejected_before_host_invocation(self):
        self.binding['session_id'] = 'v_' + 'd' * 24
        with patch('reading_tasks.visual.invoke') as host:
            with self.assertRaises(ReaderError):
                self.execute()
            host.assert_not_called()
        self.reader.source_frames.assert_not_called()

    def test_revalidation_after_host_prevents_acceptance_of_changed_material(self):
        def changed(*args, **kwargs):
            result = self.response(*args, **kwargs)
            self.reader.content.side_effect = ReaderError('Content source/speech/review changed')
            return result
        with patch('reading_tasks.visual.invoke', side_effect=changed):
            with self.assertRaisesRegex(ReaderError, 'changed'):
                self.execute()
        self.assertFalse(self.accepted_records())

    def test_historical_record_remains_readable_but_stale_prior_cannot_be_reused(self):
        with patch('reading_tasks.visual.invoke', side_effect=self.response):
            result = self.execute()
        self.reader.content.side_effect = ReaderError('Content source/speech/review changed')
        shown = self.visual.show(result['observation_id'])
        self.assertFalse(shown['current_material_valid'])
        self.assertEqual(shown['evidence_records'], result['evidence_records'])
        with self.assertRaises(ReaderError):
            self.visual.revisit(result['observation_id'])
        with patch('reading_tasks.visual.invoke') as host:
            with self.assertRaises(ReaderError):
                self.execute(464, prior_observation_ids=[result['observation_id']])
            host.assert_not_called()

    def test_non_string_prior_ids_reject_cleanly_before_job_or_host(self):
        for value in ({}, [], 123):
            with self.subTest(value=value):
                with self.assertRaises(ReaderError):
                    self.visual.start(self.session, self.index_id, '比较画面',
                        [{'timestamp_seconds': 397}], prior_observation_ids=[value])
        self.reader.job.assert_not_called()
        self.reader.source_frames.assert_not_called()

    def test_changed_observed_pixels_are_historical_only_and_cannot_be_revisited_or_reused(self):
        with patch('reading_tasks.visual.invoke', side_effect=self.response):
            result = self.execute()
        Path(self.calls[0]['images'][0]).write_bytes(b'changed source pixels')
        self.assertFalse(self.visual.show(result['observation_id'])['current_material_valid'])
        with self.assertRaises(ReaderError):
            self.visual.revisit(result['observation_id'])
        with patch('reading_tasks.visual.invoke') as host:
            with self.assertRaises(ReaderError):
                self.execute(464, prior_observation_ids=[result['observation_id']])
            host.assert_not_called()


if __name__ == '__main__':
    unittest.main()
