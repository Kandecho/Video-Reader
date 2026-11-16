"""Regression cases for local supplements, committed context and global delivery."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from PIL import Image

import test_task_consume as fixtures
from video_reader.common import ReaderError, read_json, write_json


class ConsumeContextTests(unittest.TestCase):
    # Reuse only fixture construction, not the original TestCase's test methods.
    setUp = fixtures.TaskConsumeTests.setUp

    def packet(self, prompt):
        payload = json.loads(prompt.split('\n', 1)[1])
        return payload['kind'], payload['material']

    def response(self, packet, *, notes='忠实阅读笔记', uncertainties=None,
                 evidence_requests=None, decisions=None, satisfied=True, record_text=None):
        records = []
        if record_text is not None:
            records = [{'text':record_text,
                'segment_ids':[s['segment_id'] for s in packet.get('segments', [])],
                'frame_ids':[f['id'] for f in packet.get('frames', [])]}]
        return {'packet_id':packet['packet_id'],
            'observed_segment_ids':[s['segment_id'] for s in packet.get('segments', [])],
            'observed_frame_ids':[f['id'] for f in packet.get('frames', [])],
            'summary':'有来源的任务结果', 'notes':notes,
            'uncertainties':uncertainties or [], 'evidence_requests':evidence_requests or [],
            'task_satisfied':satisfied, 'evidence_records':records,
            'uncertainty_decisions':decisions or []}

    def frame(self, identifier, second):
        path = self.root/(identifier+'.jpg')
        Image.new('RGB', (64, 32), 'blue').save(path)
        return {'id':identifier, 'path':str(path), 'time':second, 'timestamp_seconds':second}

    def test_supplement_is_local_and_does_not_replace_initial_notes(self):
        self.index['blocks'] = self.index['blocks'][:4]
        segment = self.index['blocks'][0]['segments'][0]
        segment.update(start=0, end=10, text='完整跨越补证窗口的原句，不得截断。')
        exact = self.frame('exact-proof', 5)
        self.reader.content_excerpt = Mock(return_value={
            'segments':[copy.deepcopy(segment)], 'ranges':[[0, 10]]})
        original_notes = '原包已观察到 PaymentGateway：PaymentResult pay(PaymentCommand cmd);'
        supplement_packets = []

        def host(prompt, images, schema, directory, options, **kwargs):
            kind, packet = self.packet(prompt)
            if kind == 'read':
                return self.response(packet, notes=original_notes,
                    uncertainties=['需要核定此处是否为幂等'],
                    evidence_requests=[{'start':4.5, 'end':5.5, 'timestamps':[5], 'reason':'核定关键术语'}],
                    satisfied=False, record_text=original_notes)
            if kind == 'supplement':
                supplement_packets.append(packet)
                self.assertNotIn('earlier_notes', packet)
                self.assertEqual(packet['segments'], [segment])
                self.assertEqual(packet['segments'][0]['text'], '完整跨越补证窗口的原句，不得截断。')
                self.assertEqual(packet['frames'], [exact])
                self.assertTrue(packet['evidence_requests'])
                self.assertIn(original_notes, json.dumps(packet['prior_evidence'], ensure_ascii=False))
                self.assertNotIn('完整原文3', json.dumps(packet, ensure_ascii=False))
                issue = packet['uncertainty_ledger'][0]
                decision = {'issue_id':issue['id'], 'status':'resolved', 'text':'',
                    'reason':'新源图明确写出幂等', 'evidence_ids':['new:0']}
                return self.response(packet, notes='局部补证：源图明确写幂等。',
                    record_text='源图确认该术语为幂等。', decisions=[decision])
            self.assertEqual(kind, 'synthesis')
            self.assertIn(original_notes, json.dumps(packet, ensure_ascii=False))
            self.assertIn('源图确认该术语为幂等', json.dumps(packet, ensure_ascii=False))
            return self.response(packet, notes=original_notes+'\n已由源图确认幂等。')

        run = self.consumer.start(self.item['id'])['run_id']
        with patch('reading_tasks.consume.invoke', side_effect=host), \
                patch.object(self.consumer, '_evidence', return_value=[exact]):
            result = self.consumer.execute(run)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(supplement_packets), 1)
        self.reader.content_excerpt.assert_called()
        saved = self.consumer.load(run)
        self.assertEqual(saved['observations'][0]['response']['notes'], original_notes)
        self.assertEqual(len(saved['observations'][0]['supplements']), 1)
        self.assertIn(original_notes, Path(result['artifact']).read_text(encoding='utf-8'))

    def test_later_packet_carries_committed_evidence_without_replaying_old_images(self):
        first = self.frame('first-image', 30)
        later = self.frame('later-image', 510)
        self.index['blocks'][0]['frame_refs'] = [first]
        self.index['blocks'][4]['frame_refs'] = [later]
        reads = []
        signature = 'PaymentResult pay(PaymentCommand cmd);'

        def host(prompt, images, schema, directory, options, **kwargs):
            kind, packet = self.packet(prompt)
            if kind == 'read':
                reads.append(packet)
                if len(reads) == 1:
                    return self.response(packet, notes=signature, record_text=signature)
                self.assertIn(signature, json.dumps(packet['prior_evidence'], ensure_ascii=False))
                self.assertNotIn(first['path'], images)
                self.assertNotIn(first['id'], [f['id'] for f in packet['frames']])
                record = packet['prior_evidence'][0]
                self.assertTrue(record['id'])
                self.assertEqual(record['frame_ids'], [first['id']])
                self.assertTrue(record['ranges'])
                return self.response(packet, record_text='后包的新事实。')
            return self.response(packet, notes='完整任务笔记保留支付契约：'+signature)

        run = self.consumer.start(self.item['id'])['run_id']
        with patch('reading_tasks.consume.invoke', side_effect=host):
            result = self.consumer.execute(run)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(reads), 2)

    def test_supplement_filters_unrelated_records_without_discarding_global_history(self):
        self.index['blocks'] = self.index['blocks'][:4]
        local = copy.deepcopy(self.index['blocks'][0]['segments'][0])
        far = self.index['blocks'][3]['segments'][0]
        exact = self.frame('filtered-proof', 2)
        self.reader.content_excerpt = Mock(return_value={'segments':[local], 'ranges':[[0, 8]]})
        signature = '远处已确认签名 PaymentResult pay(PaymentCommand cmd);'
        local_fact = '本地原段中的术语待源图核定。'

        def host(prompt, images, schema, directory, options, **kwargs):
            kind, packet = self.packet(prompt)
            if kind == 'read':
                response = self.response(packet, notes=signature+'\n'+local_fact,
                    uncertainties=['近处术语仍待核定'], satisfied=False,
                    evidence_requests=[{'start':1.5, 'end':2.5, 'timestamps':[2], 'reason':'核定近处术语'}])
                response['evidence_records'] = [
                    {'text':signature, 'segment_ids':[far['segment_id']], 'frame_ids':[]},
                    {'text':local_fact, 'segment_ids':[local['segment_id']], 'frame_ids':[]}]
                return response
            if kind == 'supplement':
                prior = packet['prior_evidence']
                self.assertEqual(len(prior), 1)
                self.assertEqual(prior[0]['text'], local_fact)
                self.assertNotIn(signature, json.dumps(prior, ensure_ascii=False))
                self.assertEqual(packet['segments'], [local])
                issue = packet['uncertainty_ledger'][0]
                return self.response(packet, notes='近处源图已确认幂等。',
                    record_text='局部源图核定为幂等。', decisions=[{
                        'issue_id':issue['id'], 'status':'resolved', 'text':'',
                        'reason':'精确源图支持', 'evidence_ids':['new:0']}])
            self.assertEqual(kind, 'synthesis')
            self.assertIn(signature, json.dumps(packet['prior_evidence'], ensure_ascii=False))
            self.assertIn(signature, json.dumps(packet['reading_notes'], ensure_ascii=False))
            self.assertIn('局部源图核定为幂等', json.dumps(packet['prior_evidence'], ensure_ascii=False))
            return self.response(packet, notes=signature+'\n已确认幂等。')

        run = self.consumer.start(self.item['id'])['run_id']
        with patch('reading_tasks.consume.invoke', side_effect=host), \
                patch.object(self.consumer, '_evidence', return_value=[exact]):
            result = self.consumer.execute(run)
        self.assertEqual(result['status'], 'completed')
        saved = self.consumer.load(run)
        original_records = saved['observations'][0]['evidence_records']
        self.assertEqual([record['text'] for record in original_records], [signature, local_fact])
        self.assertIn(signature, Path(result['artifact']).read_text(encoding='utf-8'))

    def test_history_frame_ids_cannot_be_claimed_as_current_observation(self):
        old = self.frame('historical-image', 30)
        self.index['blocks'][0]['frame_refs'] = [old]
        count = 0

        def host(prompt, images, schema, directory, options, **kwargs):
            nonlocal count
            kind, packet = self.packet(prompt)
            response = self.response(packet, record_text='已接受的画面事实')
            if kind == 'read':
                count += 1
                if count == 2:
                    response['observed_frame_ids'].append(old['id'])
            return response

        run = self.consumer.start(self.item['id'])['run_id']
        with patch('reading_tasks.consume.invoke', side_effect=host):
            with self.assertRaisesRegex(ReaderError, 'observation IDs'):
                self.consumer.execute(run)
        self.assertEqual(self.consumer.load(run)['next_block'], 4)

    def test_read_with_material_cannot_accept_empty_evidence_records(self):
        run = self.consumer.start(self.item['id'])['run_id']

        def empty_records(prompt, images, schema, directory, options, **kwargs):
            kind, packet = self.packet(prompt)
            self.assertEqual(kind, 'read')
            self.assertTrue(packet['segments'] or packet['frames'])
            return self.response(packet, notes='虽然写了笔记，但没有可接续的证据记录。')

        with patch('reading_tasks.consume.invoke', side_effect=empty_records):
            with self.assertRaises(ReaderError):
                self.consumer.execute(run)
        saved = self.consumer.load(run)
        self.assertEqual(saved['next_block'], 0)
        self.assertEqual(saved['observations'], [])
        self.assertEqual(self.consumer.queue.show(self.item['id'])['state'], 'pending')

    def test_failed_supplement_resume_reuses_pending_read_without_repeating_initial_host(self):
        self.index['blocks'] = self.index['blocks'][:4]
        local = copy.deepcopy(self.index['blocks'][0]['segments'][0])
        exact = self.frame('resume-proof', 2)
        self.reader.content_excerpt = Mock(return_value={'segments':[local], 'ranges':[[0, 8]]})
        original_notes = '初读已确认 PaymentResult pay(PaymentCommand cmd);，保留原笔记。'
        kinds = []

        def interrupted(prompt, images, schema, directory, options, **kwargs):
            kind, packet = self.packet(prompt)
            kinds.append(kind)
            if kind == 'read':
                return self.response(packet, notes=original_notes,
                    record_text=original_notes, uncertainties=['关键术语仍待核定'],
                    evidence_requests=[{'start':1, 'end':3, 'timestamps':[2], 'reason':'核定术语'}],
                    satisfied=False)
            self.assertEqual(kind, 'supplement')
            raise ReaderError('supplement transport fixture')

        run = self.consumer.start(self.item['id'])['run_id']
        with patch('reading_tasks.consume.invoke', side_effect=interrupted), \
                patch.object(self.consumer, '_evidence', return_value=[exact]):
            with self.assertRaisesRegex(ReaderError, 'supplement transport'):
                self.consumer.execute(run)
        saved = self.consumer.load(run)
        self.assertEqual(saved['next_block'], 0)
        self.assertEqual(saved['observations'], [])
        self.assertTrue(saved.get('pending_read'))
        self.assertIn(original_notes, json.dumps(saved['pending_read'], ensure_ascii=False))
        original_paths = list(self.consumer.directory(run).glob('attempts/*/accepted.json'))
        self.assertEqual(len(original_paths), 1)
        original_bytes = original_paths[0].read_bytes()

        def resumed(prompt, images, schema, directory, options, **kwargs):
            kind, packet = self.packet(prompt)
            kinds.append(kind)
            if kind == 'supplement':
                self.assertIn(original_notes, json.dumps(packet['prior_evidence'], ensure_ascii=False))
                issue = packet['uncertainty_ledger'][0]
                return self.response(packet, notes='补证确认术语为幂等。',
                    record_text='精确源图确认幂等。', decisions=[{
                        'issue_id':issue['id'], 'status':'resolved', 'text':'',
                        'reason':'源图直接支持', 'evidence_ids':['new:0']}])
            self.assertEqual(kind, 'synthesis')
            return self.response(packet, notes=original_notes+'\n局部补证已确认幂等。')

        with patch('reading_tasks.consume.invoke', side_effect=resumed), \
                patch.object(self.consumer, '_evidence', return_value=[exact]):
            result = self.consumer.execute(run)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(kinds, ['read', 'supplement', 'supplement', 'synthesis'])
        self.assertEqual(original_paths[0].read_bytes(), original_bytes)
        final_state = self.consumer.load(run)
        self.assertFalse(final_state.get('pending_read'))
        self.assertEqual(final_state['observations'][0]['response']['notes'], original_notes)
        self.assertIn(original_notes, Path(result['artifact']).read_text(encoding='utf-8'))

    def test_final_evidence_decision_removes_stage_limit_but_retains_real_unknown(self):
        reads = 0

        def host(prompt, images, schema, directory, options, **kwargs):
            nonlocal reads
            kind, packet = self.packet(prompt)
            if kind == 'read':
                reads += 1
                issues = ['本包仅覆盖0–480秒，前后文尚未交付', '外部事实仍缺少独立核查'] if reads == 1 else []
                return self.response(packet, uncertainties=issues,
                    record_text='该时间范围已观察的事实。')
            ledger = packet['uncertainty_ledger']
            self.assertEqual(len(ledger), 2)
            self.assertEqual(len(packet['prior_evidence']), 2)
            evidence_ids = [record['id'] for record in packet['prior_evidence']]
            decisions = []
            for issue in ledger:
                if '本包' in issue['text']:
                    decisions.append({'issue_id':issue['id'], 'status':'resolved', 'text':'',
                        'reason':'前后两包均已观察，并有各自原段支持；对应事实已补齐',
                        'evidence_ids':evidence_ids})
                else:
                    decisions.append({'issue_id':issue['id'], 'status':'retain',
                        'text':'外部事实缺少独立核查。', 'reason':'视频自述不是独立核实', 'evidence_ids':[]})
            return self.response(packet, notes='根据全部已读材料整理的任务笔记。',
                decisions=decisions, satisfied=False)

        run = self.consumer.start(self.item['id'])['run_id']
        with patch('reading_tasks.consume.invoke', side_effect=host):
            result = self.consumer.execute(run)
        self.assertEqual(result['status'], 'needs_attention')
        self.assertEqual(result['task']['state'], 'pending')
        artifact = Path(result['artifact']).read_text(encoding='utf-8')
        self.assertNotIn('本包仅覆盖', artifact)
        self.assertIn('外部事实缺少独立核查', artifact)
        self.assertIn('本包仅覆盖', self.consumer.load(run)['observations'][0]['response']['uncertainties'][0])

    def assert_coverage_cannot_resolve_external_unknown(self, decision_status):
        reads = 0

        def host(prompt, images, schema, directory, options, **kwargs):
            nonlocal reads
            kind, packet = self.packet(prompt)
            if kind == 'read':
                reads += 1
                return self.response(packet,
                    uncertainties=['外部事实尚未独立核查'] if reads == 1 else [],
                    record_text='视频中的陈述，仅代表作者说法。')
            issue = packet['uncertainty_ledger'][0]
            return self.response(packet, notes='不应据完整交付冒称已完成外部核查。',
                decisions=[{'issue_id':issue['id'], 'status':decision_status, 'text':'',
                    'reason':'所有包都已交付', 'evidence_ids':['coverage']}])

        run = self.consumer.start(self.item['id'])['run_id']
        with patch('reading_tasks.consume.invoke', side_effect=host):
            with self.assertRaises(ReaderError):
                self.consumer.execute(run)
        self.assertEqual(self.consumer.load(run)['next_block'], 8)
        self.assertEqual(self.consumer.queue.show(self.item['id'])['state'], 'pending')
        with self.consumer.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM task_results').fetchone()[0], 0)

    def test_scope_coverage_cannot_discard_external_fact_check(self):
        self.assert_coverage_cannot_resolve_external_unknown('scope')

    def test_resolved_requires_concrete_evidence_not_coverage_metadata(self):
        self.assert_coverage_cannot_resolve_external_unknown('resolved')

    def test_synthesis_cannot_silently_omit_an_existing_uncertainty(self):
        reads = 0

        def host(prompt, images, schema, directory, options, **kwargs):
            nonlocal reads
            kind, packet = self.packet(prompt)
            if kind == 'read':
                reads += 1
                return self.response(packet, uncertainties=['关键数字仍未核定'] if reads == 1 else [],
                    record_text='有来源的观察记录。')
            self.assertTrue(packet['uncertainty_ledger'])
            return self.response(packet, notes='不应静默删掉疑点的终稿', decisions=[])

        run = self.consumer.start(self.item['id'])['run_id']
        with patch('reading_tasks.consume.invoke', side_effect=host):
            with self.assertRaises(ReaderError):
                self.consumer.execute(run)
        self.assertEqual(self.consumer.load(run)['next_block'], 8)
        self.assertEqual(self.consumer.queue.show(self.item['id'])['state'], 'pending')
        with self.consumer.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM task_results').fetchone()[0], 0)

    def test_rejected_checkpoint_does_not_leak_accepted_file_into_later_context(self):
        run = self.consumer.start(self.item['id'])['run_id']
        read_count = 0
        save = self.consumer.save

        def host(prompt, images, schema, directory, options, **kwargs):
            nonlocal read_count
            kind, packet = self.packet(prompt)
            if kind == 'read':
                read_count += 1
                text = '首包已经提交的支付事实' if read_count == 1 else '未通过检查点的孤立观察'
                return self.response(packet, notes=text, record_text=text)
            return self.response(packet)

        def rejected(state, status=None, **kwargs):
            if state.get('next_block') == 8 and len(state.get('observations', [])) == 2:
                raise ReaderError('checkpoint rejected fixture')
            return save(state, status, **kwargs)

        with patch('reading_tasks.consume.invoke', side_effect=host), \
                patch.object(self.consumer, 'save', side_effect=rejected):
            with self.assertRaisesRegex(ReaderError, 'checkpoint rejected'):
                self.consumer.execute(run)
        saved = self.consumer.load(run)
        self.assertEqual(saved['next_block'], 4)
        accepted_paths = list(self.consumer.directory(run).glob('attempts/*/accepted.json'))
        self.assertTrue(any('未通过检查点' in read_json(p)['response']['notes'] for p in accepted_paths))

        def resumed(prompt, images, schema, directory, options, **kwargs):
            kind, packet = self.packet(prompt)
            if kind == 'read':
                prior = json.dumps(packet['prior_evidence'], ensure_ascii=False)
                self.assertIn('首包已经提交的支付事实', prior)
                self.assertNotIn('未通过检查点的孤立观察', prior)
            return self.response(packet, record_text='恢复后的有效观察' if kind == 'read' else None)

        with patch('reading_tasks.consume.invoke', side_effect=resumed):
            result = self.consumer.execute(run)
        self.assertEqual(result['status'], 'completed')

    def test_legacy_checkpoint_recovers_original_read_without_changing_old_files(self):
        run = self.consumer.start(self.item['id'])['run_id']
        reads = 0
        signature = '历史首包保留的方法签名 PaymentResult pay(PaymentCommand cmd);'

        def interrupted(prompt, images, schema, directory, options, **kwargs):
            nonlocal reads
            kind, packet = self.packet(prompt)
            if kind == 'read':
                reads += 1
                if reads == 2:
                    raise ReaderError('legacy interruption fixture')
                return self.response(packet, notes=signature, record_text=signature)
            return self.response(packet)

        with patch('reading_tasks.consume.invoke', side_effect=interrupted):
            with self.assertRaisesRegex(ReaderError, 'legacy interruption'):
                self.consumer.execute(run)
        state = self.consumer.load(run)
        original = self.consumer.directory(run)/'attempts'/state['observations'][0]['attempt_id']/'accepted.json'
        before = original.read_bytes()
        state.pop('context_version', None)
        state['observations'][0].pop('context_version', None)
        legacy_response = copy.deepcopy(state['observations'][0]['response'])
        legacy_response['notes'] = '旧实现用局部补证覆盖过的笔记'
        legacy_response.pop('evidence_records', None)
        legacy_response.pop('uncertainty_decisions', None)
        legacy_attempt = 'c'*32
        legacy_directory = self.consumer.directory(run)/'attempts'/legacy_attempt
        legacy_packet = read_json(original.parent/'packet.json')
        write_json(legacy_directory/'packet.json', legacy_packet)
        write_json(legacy_directory/'accepted.json', {'attempt_id':legacy_attempt,
            'packet_id':legacy_packet['packet_id'], 'response':legacy_response})
        state['observations'][0]['response'] = legacy_response
        state['observations'][0]['supplements'] = [{'attempt_id':legacy_attempt,
            'packet_id':legacy_packet['packet_id'], 'response':legacy_response,
            'segment_ids':legacy_response['observed_segment_ids'],
            'frame_ids':legacy_response['observed_frame_ids']}]
        for key in ('evidence_records', 'uncertainty_decisions', 'uncertainty_issues'):
            state['observations'][0].pop(key, None)
        self.consumer.save(state, 'failed')

        def resumed(prompt, images, schema, directory, options, **kwargs):
            kind, packet = self.packet(prompt)
            if kind == 'read':
                self.assertIn(signature, json.dumps(packet['prior_evidence'], ensure_ascii=False))
            return self.response(packet, record_text='后续有效观察' if kind == 'read' else None)

        with patch('reading_tasks.consume.invoke', side_effect=resumed):
            result = self.consumer.execute(run)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(original.read_bytes(), before)

    def legacy_supplement_checkpoint(self, *, complete_reading=False, old_final=False):
        run = self.consumer.start(self.item['id'])['run_id']
        state = self.consumer.load(run)
        self.consumer._prepare(state)
        signature = '已接受的原始方法签名 PaymentResult pay(PaymentCommand cmd);'
        groups = [self.index['blocks'][:4]]
        if complete_reading:
            groups.append(self.index['blocks'][4:])
        observations = []
        first_accepted = None
        for index, group in enumerate(groups):
            attempt = str(index+1)*32
            packet = {'packet_id':'legacy-packet-'+str(index), 'source':state['canonical'],
                'index_id':state['index_id'], 'ranges':[[b['start'],b['end']] for b in group],
                'segments':[segment for block in group for segment in block['segments']],
                'frames':[], 'gaps':[]}
            response = self.response(packet, notes=signature if index == 0 else '后包已接受的原始事实。')
            response.pop('evidence_records')
            response.pop('uncertainty_decisions')
            directory = self.consumer.directory(run)/'attempts'/attempt
            write_json(directory/'packet.json', packet)
            write_json(directory/'accepted.json', {'attempt_id':attempt,
                'packet_id':packet['packet_id'], 'response':response})
            observation = {'attempt_id':attempt, 'packet_id':packet['packet_id'],
                'response':response, 'segment_ids':response['observed_segment_ids'], 'frame_ids':[]}
            if index == 0:
                first_accepted = directory/'accepted.json'
                supplement = copy.deepcopy(response)
                supplement['notes'] = '旧版补证覆盖值，只记局部术语。'
                supplemental_attempt = '9'*32
                supplemental_directory = self.consumer.directory(run)/'attempts'/supplemental_attempt
                write_json(supplemental_directory/'packet.json', packet)
                write_json(supplemental_directory/'accepted.json', {'attempt_id':supplemental_attempt,
                    'packet_id':packet['packet_id'], 'response':supplement})
                observation['response'] = supplement
                observation['supplements'] = [{'attempt_id':supplemental_attempt,
                    'packet_id':packet['packet_id'], 'response':supplement,
                    'segment_ids':supplement['observed_segment_ids'], 'frame_ids':[]}]
            observations.append(observation)
        state.update(observations=observations, next_block=8 if complete_reading else 4,
            phase='committing_result' if old_final else 'reading')
        state.pop('context_version', None)
        if old_final:
            state['final_kind'] = 'synthesis'
            state['final'] = {'attempt_id':'8'*32, 'packet_id':'legacy-final',
                'response':self.response({'packet_id':'legacy-final'}, notes='不应直接提交的旧终稿。')}
        self.consumer.save(state, 'failed')
        return run, signature, first_accepted

    def test_legacy_supplement_without_initial_accepted_cannot_resume(self):
        run, signature, first_accepted = self.legacy_supplement_checkpoint()
        first_accepted.unlink()
        with patch('reading_tasks.consume.invoke', side_effect=AssertionError('missing original must stop before host')):
            with self.assertRaisesRegex(ReaderError, 'missing.*original accepted'):
                self.consumer.execute(run)
        self.assertEqual(self.consumer.load(run)['next_block'], 4)
        self.assertEqual(self.consumer.queue.show(self.item['id'])['state'], 'pending')

    def test_uncommitted_legacy_final_is_reorganized_and_preserved(self):
        run, signature, first_accepted = self.legacy_supplement_checkpoint(
            complete_reading=True, old_final=True)
        old_final = copy.deepcopy(self.consumer.load(run)['final'])
        before = first_accepted.read_bytes()
        kinds = []

        def host(prompt, images, schema, directory, options, **kwargs):
            kind, packet = self.packet(prompt)
            kinds.append(kind)
            self.assertEqual(kind, 'synthesis')
            self.assertIn(signature, json.dumps(packet['reading_notes'], ensure_ascii=False))
            self.assertIn(signature, json.dumps(packet['prior_evidence'], ensure_ascii=False))
            return self.response(packet, notes='新整理已保留原始证据：'+signature)

        with patch('reading_tasks.consume.invoke', side_effect=host):
            result = self.consumer.execute(run)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(kinds, ['synthesis'])
        saved = self.consumer.load(run)
        self.assertEqual(saved['legacy_final'], old_final)
        self.assertEqual(saved['final']['context_version'], 2)
        self.assertEqual(first_accepted.read_bytes(), before)
        artifact = Path(result['artifact']).read_text(encoding='utf-8')
        self.assertIn(signature, artifact)
        self.assertNotIn('不应直接提交的旧终稿', artifact)


if __name__ == '__main__':
    unittest.main()
