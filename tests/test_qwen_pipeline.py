from types import SimpleNamespace
import unittest

from video_reader.qwen_pipeline import cer, chunk_plan, owned_chunk, seam_diagnostics, stitch_chunks, transcribe


def unit(text, start, end):
    return SimpleNamespace(text=text, start_time=start, end_time=end)


class QwenFoundationTests(unittest.TestCase):
    def test_cer_identity_and_punctuation(self):
        self.assertEqual(cer('你，好！Ａ 123', '你好a123')['cer'], 0)

    def test_cer_edits(self):
        result = cer('甲乙丙', '甲丁丙戊')
        self.assertEqual((result['errors'], result['substitutions'], result['insertions']), (2, 1, 1))
        self.assertEqual(cer('甲乙丙', '甲丙')['deletions'], 1)

    def test_cer_empty_and_numeric_forms(self):
        self.assertIsNone(cer('', '甲')['cer'])
        self.assertEqual(cer('', '')['cer'], 0)
        self.assertGreater(cer('三', '3')['cer'], 0)

    def test_short_and_tail(self):
        self.assertEqual(chunk_plan(10, 10)[0]['input_end'], 10)
        plans = chunk_plan(2501, 10, 120)
        self.assertEqual([(plan['owner_start'], plan['owner_end']) for plan in plans],
                         [(0, 1200), (1200, 2400), (2400, 2501)])
        self.assertEqual(plans[1]['input_start'], 1180)
        self.assertEqual(plans[-1]['input_end'], 2501)

    def test_invalid_plans(self):
        for values in [(0, 10, 120, 2), (10, 0, 120, 2), (10, 10, 0, 2),
                       (10, 10, float('nan'), 2), (10, 10, 121, 2), (10, 10, 120, -1)]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                chunk_plan(*values)

    def test_midpoint_crossing_and_exact_boundary(self):
        plans = chunk_plan(40, 10, 2, 1)
        left = owned_chunk('甲乙', [unit('甲', 1.7, 2.1), unit('乙', 2.1, 2.2)], plans[0], 10)
        right = owned_chunk('甲乙', [unit('甲', 0.7, 1.1), unit('乙', 1.1, 1.2)], plans[1], 10)
        self.assertEqual(left['text'], '甲')
        self.assertEqual(right['text'], '乙')
        self.assertEqual(right['words'][0]['start'], 2.1)
        self.assertEqual(owned_chunk('丙', [unit('丙', 1.9, 2.1)], plans[0], 10)['text'], '')
        self.assertEqual(owned_chunk('丙', [unit('丙', 0.9, 1.1)], plans[1], 10)['text'], '丙')

    def test_real_repetition_is_not_string_deduplicated(self):
        plan = chunk_plan(40, 10)[0]
        result = owned_chunk('是，是。', [unit('是', 0.2, 0.3), unit('是', 0.4, 0.5)], plan, 10)
        self.assertEqual(result['text'], '是，是。')
        self.assertEqual(len(result['words']), 2)

    def test_punctuation_mixed_latin_and_absolute_offset(self):
        plan = chunk_plan(60, 10)[0]
        result = owned_chunk('“U.S. AI，好！”', [unit('US', 0.1, 0.5), unit('AI', 0.6, 1),
            unit('好', 1.2, 1.5)], plan, 10, 16)
        self.assertEqual(result['text'], '“U.S. AI，好！”')
        self.assertEqual(result['words'][0]['start'], 16.1)
        self.assertEqual(result['words'][-1]['end'], 17.5)

    def test_invalid_alignment_is_rejected(self):
        plan = chunk_plan(10, 10)[0]
        for items in [[unit('甲', 1, 2)], [unit('甲', -1, 0)], [unit('甲', float('nan'), 0)],
                      [unit('乙', 0, 1)], [unit('甲', 0.8, 0.1)]]:
            with self.subTest(items=items), self.assertRaises(ValueError):
                owned_chunk('甲', items, plan, 10)

    def test_zero_duration_is_disclosed(self):
        result = owned_chunk('甲', [unit('甲', 0, 0)], chunk_plan(10, 10)[0], 10)
        self.assertEqual(result['warnings'][0]['kind'], 'zero_duration_unit')

    def test_silence(self):
        result = owned_chunk('', [], chunk_plan(10, 10)[0], 10)
        self.assertEqual((result['text'], result['words']), ('', []))

    def test_seam_disagreement_is_preserved(self):
        plans = chunk_plan(40, 10, 2, 1)
        left = owned_chunk('甲', [unit('甲', 1.8, 1.9)], plans[0], 10)
        right = owned_chunk('乙', [unit('乙', 1.1, 1.2)], plans[1], 10)
        seam = seam_diagnostics([left, right])[0]
        self.assertTrue(seam['disagreement'])

    def test_pipeline_requests_alignment_without_reference_prompt(self):
        class Model:
            def transcribe(self, **kwargs):
                self.kwargs = kwargs
                return [SimpleNamespace(text='好。', time_stamps=[unit('好', 0.1, 0.2)])]
        model = Model()
        result = transcribe(model, [0] * 10, 10)
        self.assertEqual(result['text'], '好。')
        self.assertEqual(model.kwargs['context'], '')
        self.assertTrue(model.kwargs['return_time_stamps'])
        self.assertIsNone(model.kwargs['language'])
        forced = transcribe(model, [0] * 10, 10, language='Chinese')
        self.assertEqual(model.kwargs['language'], 'Chinese')
        self.assertEqual(forced['profile']['language'], 'Chinese')

    def test_raw_generation_and_token_limit_survive_parser_collapse(self):
        from video_reader.qwen_pipeline import decode_with_diagnostics
        raw = '爱，'*30
        class Processor:
            def batch_decode(self, tokens, **kwargs):
                return [raw]
        class Model:
            processor = Processor()
            max_new_tokens = 60
            def transcribe(self, **kwargs):
                self.processor.batch_decode([list(range(60))])
                return [SimpleNamespace(language='Chinese', text='爱，', time_stamps=[])]
        model = Model()
        original = model.processor.batch_decode
        output, generation = decode_with_diagnostics(model, ([0]*10, 10), language='Chinese')
        self.assertEqual(output.text, '爱，')
        self.assertEqual(generation['outputs'][0]['raw_output'], raw)
        self.assertEqual(generation['generated_tokens'], 60)
        self.assertTrue(generation['limit_reached'])
        self.assertTrue(generation['postprocessing_changed_text'])
        self.assertEqual(model.processor.batch_decode, original)

    def test_capture_restores_processor_after_failed_alignment(self):
        from video_reader.qwen_pipeline import decode_with_diagnostics
        processor = SimpleNamespace(batch_decode=lambda *args: ['原文'])
        original = processor.batch_decode
        def failed(**kwargs):
            raise ValueError('alignment failed')
        model = SimpleNamespace(processor=processor, max_new_tokens=4096, transcribe=failed)
        with self.assertRaisesRegex(ValueError, 'alignment failed'):
            decode_with_diagnostics(model, ([0]*10, 10))
        self.assertIs(processor.batch_decode, original)

    def test_same_text_can_still_have_conflicting_seam_times(self):
        plans = chunk_plan(40, 10, 2, 1)
        left = owned_chunk('甲', [unit('甲', 1.7, 2.1)], plans[0], 10)
        right = owned_chunk('甲', [unit('甲', 0.9, 1.3)], plans[1], 10)
        seam = seam_diagnostics([left, right])[0]
        self.assertFalse(seam['disagreement'])
        self.assertTrue(seam['requires_review'])
        self.assertEqual(seam['owned_time_overlap_seconds'], 0.2)

    def test_shared_pair_removes_timestamp_drift_duplicate(self):
        plans = chunk_plan(40, 10, 2, 1)
        left = owned_chunk('发表声明', [unit('发', 1.5, 1.7), unit('表', 1.7, 2.1),
            unit('声', 2.1, 2.3), unit('明', 2.3, 2.5)], plans[0], 10)
        right = owned_chunk('发表声明', [unit('发', 0.5, 0.7), unit('表', 0.9, 1.2),
            unit('声', 1.2, 1.4), unit('明', 1.4, 1.6)], plans[1], 10)
        self.assertEqual(left['text'] + right['text'], '发表表声明')
        chunks, cuts = stitch_chunks([left, right])
        self.assertEqual(''.join(chunk['text'] for chunk in chunks), '发表声明')
        self.assertEqual(cuts[0]['method'], 'unique_shared_pair')
        self.assertEqual(left['text'] + right['text'], '发表表声明')

    def test_shared_pair_recovers_midpoint_gap(self):
        plans = chunk_plan(40, 10, 2, 1)
        left = owned_chunk('发表声明', [unit('发', 1.5, 1.7), unit('表', 1.9, 2.2),
            unit('声', 2.2, 2.4), unit('明', 2.4, 2.6)], plans[0], 10)
        right = owned_chunk('发表声明', [unit('发', 0.5, 0.7), unit('表', 0.7, 1.1),
            unit('声', 1.1, 1.3), unit('明', 1.3, 1.5)], plans[1], 10)
        self.assertEqual(left['text'] + right['text'], '发声明')
        chunks, cuts = stitch_chunks([left, right])
        self.assertEqual(''.join(chunk['text'] for chunk in chunks), '发表声明')

    def test_shared_seam_preserves_true_repetition(self):
        plans = chunk_plan(40, 10, 2, 1)
        left = owned_chunk('是是的', [unit('是', 1.7, 1.8), unit('是', 1.9, 2.1),
            unit('的', 2.2, 2.4)], plans[0], 10)
        right = owned_chunk('是是的', [unit('是', 0.7, 0.8), unit('是', 0.9, 1.1),
            unit('的', 1.2, 1.4)], plans[1], 10)
        chunks, cuts = stitch_chunks([left, right])
        self.assertEqual(''.join(chunk['text'] for chunk in chunks), '是是的')

    def test_shared_seam_does_not_match_remote_repeated_phrase(self):
        plans = chunk_plan(60, 10, 3, 1)
        left = owned_chunk('你好', [unit('你', 0.2, 0.4), unit('好', 0.5, 0.7)], plans[0], 10)
        right = owned_chunk('你好', [unit('你', 1.2, 1.4), unit('好', 1.5, 1.7)], plans[1], 10)
        chunks, cuts = stitch_chunks([left, right])
        self.assertEqual(''.join(chunk['text'] for chunk in chunks), '你好你好')
        self.assertEqual(cuts[0]['method'], 'midpoint_fallback')

    def test_float_roundoff_does_not_request_review(self):
        plans = chunk_plan(40, 10, 2, 1)
        left = owned_chunk('甲', [unit('甲', 1.8, 2.0000000000001)], plans[0], 10)
        right = owned_chunk('甲', [unit('甲', 1, 1.2)], plans[1], 10)
        self.assertFalse(seam_diagnostics([left, right])[0]['requires_review'])

    def test_ambiguous_rapid_repetition_keeps_midpoint_fallback(self):
        plans = chunk_plan(40, 10, 2, 1)
        left = owned_chunk('甲甲甲', [unit('甲', 1.8, 1.9), unit('甲', 1.9, 2),
            unit('甲', 2, 2.1)], plans[0], 10)
        right = owned_chunk('甲甲甲', [unit('甲', 0.8, 0.9), unit('甲', 0.9, 1),
            unit('甲', 1, 1.1)], plans[1], 10)
        chunks, cuts = stitch_chunks([left, right])
        self.assertEqual(''.join(chunk['text'] for chunk in chunks), '甲甲甲')
        self.assertEqual(cuts[0]['method'], 'midpoint_fallback')


if __name__ == '__main__':
    unittest.main()
