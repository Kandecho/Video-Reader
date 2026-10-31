from __future__ import annotations

import math
import time
import unicodedata


def normalize(text):
    return ''.join(character for character in unicodedata.normalize('NFKC', text).casefold()
                   if not character.isspace() and not unicodedata.category(character).startswith('P'))


def cer(reference, hypothesis):
    reference, hypothesis = normalize(reference), normalize(hypothesis)
    previous = [(column, 0, 0, column) for column in range(len(hypothesis) + 1)]
    for row, expected in enumerate(reference, 1):
        current = [(row, 0, row, 0)]
        for column, actual in enumerate(hypothesis, 1):
            if expected == actual:
                current.append(previous[column - 1])
                continue
            diagonal, above, left = previous[column - 1], previous[column], current[column - 1]
            candidates = [(diagonal[0] + 1, diagonal[1] + 1, diagonal[2], diagonal[3]),
                          (above[0] + 1, above[1], above[2] + 1, above[3]),
                          (left[0] + 1, left[1], left[2], left[3] + 1)]
            current.append(min(candidates, key=lambda candidate: candidate[0]))
        previous = current
    errors, substitutions, deletions, insertions = previous[-1]
    return {'characters': len(reference), 'errors': errors, 'substitutions': substitutions,
            'deletions': deletions, 'insertions': insertions,
            'cer': errors / len(reference) if reference else (0.0 if not hypothesis else None)}


def chunk_plan(samples, sample_rate, chunk_seconds=60, overlap_seconds=2):
    if samples <= 0 or sample_rate <= 0:
        raise ValueError('Audio and sample rate must be positive')
    if not math.isfinite(chunk_seconds) or not 0 < chunk_seconds <= 120:
        raise ValueError('Chunk duration must be positive and at most 120 seconds')
    if not math.isfinite(overlap_seconds) or not 0 <= overlap_seconds <= 10:
        raise ValueError('Overlap must be between 0 and 10 seconds')
    width = round(chunk_seconds * sample_rate)
    padding = round(overlap_seconds * sample_rate)
    if width < 1:
        raise ValueError('Chunk duration must contain at least one sample')
    return [{'index': index, 'owner_start': start, 'owner_end': min(start + width, samples),
             'input_start': max(0, start - padding), 'input_end': min(samples, start + width + padding)}
            for index, start in enumerate(range(0, samples, width))]


def kept(character):
    return character == "'" or unicodedata.category(character).startswith(('L', 'N'))


def owned_chunk(raw_text, items, plan, sample_rate, offset_seconds=0):
    positions = [index for index, character in enumerate(raw_text) if kept(character)]
    cleaned = ''.join(raw_text[index] for index in positions)
    if cleaned != ''.join(item.text for item in items):
        raise ValueError('Aligner units do not match the original decoded text')
    duration = (plan['input_end'] - plan['input_start']) / sample_rate
    owner_start, owner_end = plan['owner_start'] / sample_rate, plan['owner_end'] / sample_rate
    window_start = plan['input_start'] / sample_rate
    words, selected, warnings = [], [], []
    cursor, previous_end = 0, 0.0
    for index, item in enumerate(items):
        local_start, local_end = float(item.start_time), float(item.end_time)
        if not all(math.isfinite(value) for value in (local_start, local_end)):
            raise ValueError('Non-finite alignment timestamp')
        if not 0 <= local_start <= local_end <= duration + 0.001:
            raise ValueError(f'Alignment outside input audio: {local_start}, {local_end}, {duration}')
        if local_start < previous_end:
            raise ValueError('Non-monotonic alignment timestamps')
        if local_start == local_end:
            warnings.append({'kind': 'zero_duration_unit', 'index': index, 'text': item.text})
        previous_end = local_end
        midpoint = window_start + (local_start + local_end) / 2
        included = owner_start <= midpoint < owner_end
        words.append({'text': item.text, 'start': offset_seconds + window_start + local_start,
                      'end': offset_seconds + window_start + local_end, 'owned': included,
                      'text_start': positions[cursor],
                      'text_end': positions[cursor + len(item.text) - 1] + 1})
        cursor += len(item.text)
        if included:
            selected.append(index)
    if selected and selected != list(range(selected[0], selected[-1] + 1)):
        raise ValueError('Non-contiguous ownership')
    if selected:
        first, last = selected[0], selected[-1]
        text_start = 0 if first == 0 else words[first]['text_start']
        text_end = words[last + 1]['text_start'] if last + 1 < len(words) else len(raw_text)
        text = raw_text[text_start:text_end].strip()
    else:
        text = ''
    return {'index': plan['index'], 'owner': [offset_seconds + owner_start, offset_seconds + owner_end],
            'input': [offset_seconds + window_start, offset_seconds + plan['input_end'] / sample_rate],
            'raw_text': raw_text, 'text': text, 'raw_words': words,
            'words': [word for word in words if word['owned']], 'warnings': warnings}


def seam_diagnostics(chunks):
    seams = []
    for left, right in zip(chunks, chunks[1:]):
        boundary = left['owner'][1]
        readings = []
        for chunk in (left, right):
            readings.append(''.join(word['text'] for word in chunk['raw_words']
                                   if boundary - 0.8 <= (word['start'] + word['end']) / 2 < boundary + 0.8))
        overlap = round(max(0.0, left['words'][-1]['end'] - right['words'][0]['start']), 6) if left['words'] and right['words'] else 0.0
        disagreement = normalize(readings[0]) != normalize(readings[1])
        seams.append({'time': boundary, 'left_reading': readings[0], 'right_reading': readings[1],
                      'disagreement': disagreement, 'owned_time_overlap_seconds': round(overlap, 6),
                      'requires_review': disagreement or overlap > 0,
                      'resolution': 'midpoint ownership; disagreement is not silently corrected'})
    return seams


def stitch_chunks(chunks):
    bounds = []
    for chunk in chunks:
        selected = [index for index, word in enumerate(chunk['raw_words']) if word['owned']]
        bounds.append([selected[0], selected[-1] + 1] if selected else [0, 0])
    cuts = []
    for index, (left, right) in enumerate(zip(chunks, chunks[1:])):
        boundary = left['owner'][1]
        matches = []
        for left_index in range(len(left['raw_words']) - 1):
            left_pair = left['raw_words'][left_index:left_index + 2]
            left_cut = (left_pair[0]['end'] + left_pair[1]['start']) / 2
            if abs(left_cut - boundary) > 0.5:
                continue
            for right_index in range(len(right['raw_words']) - 1):
                right_pair = right['raw_words'][right_index:right_index + 2]
                right_cut = (right_pair[0]['end'] + right_pair[1]['start']) / 2
                if abs(right_cut - boundary) > 0.5:
                    continue
                if [word['text'] for word in left_pair] != [word['text'] for word in right_pair]:
                    continue
                if any(word['end'] <= word['start'] for word in left_pair + right_pair):
                    continue
                drift = max(abs((first['start'] + first['end'] - second['start'] - second['end']) / 2)
                            for first, second in zip(left_pair, right_pair))
                if drift <= 0.25:
                    matches.append({'left': left_index, 'right': right_index,
                                    'canonical_time': (left_cut + right_cut) / 2, 'drift': drift})
        unique = [match for match in matches
                  if sum(other['left'] == match['left'] for other in matches) == 1
                  and sum(other['right'] == match['right'] for other in matches) == 1
                  and match['left'] + 1 >= bounds[index][0]
                  and match['right'] + 1 <= bounds[index + 1][1]
                  and match['left'] <= bounds[index][1] <= match['left'] + 2
                  and match['right'] <= bounds[index + 1][0] <= match['right'] + 2
                  and any(left['raw_words'][match['left'] + shift]['owned'] ==
                          right['raw_words'][match['right'] + shift]['owned'] for shift in (0, 1))]
        if unique:
            chosen = min(unique, key=lambda match: (abs(match['canonical_time'] - boundary), match['drift']))
            bounds[index][1] = chosen['left'] + 1
            bounds[index + 1][0] = chosen['right'] + 1
            cuts.append({'time': boundary, 'method': 'unique_shared_pair', **chosen})
        else:
            cuts.append({'time': boundary, 'method': 'midpoint_fallback',
                         'reason': 'No unambiguous shared pair with a local midpoint ownership conflict'})
    stitched = []
    for chunk, (first, stop) in zip(chunks, bounds):
        raw_words = chunk['raw_words']
        if stop > first:
            start = 0 if first == 0 else raw_words[first]['text_start']
            end = raw_words[stop]['text_start'] if stop < len(raw_words) else len(chunk['raw_text'])
            text = chunk['raw_text'][start:end].strip()
        else:
            text = ''
        stitched.append({**chunk, 'midpoint_text': chunk.get('midpoint_text', chunk['text']),
                         'text': text, 'selected_raw_indices': [first, stop],
                         'words': [{**word, 'midpoint_owned': word['owned'], 'owned': True}
                                   for word in raw_words[first:stop]]})
    return stitched, cuts


def load_model(root, model_path=None, aligner_path=None):
    import torch
    from qwen_asr import Qwen3ASRModel
    torch.set_num_threads(4)
    options = {'dtype': torch.float16, 'device_map': 'cuda:0', 'attn_implementation': 'sdpa',
               'local_files_only': True}
    return Qwen3ASRModel.from_pretrained(str(model_path or root / 'models/Qwen3-ASR-0.6B'),
        **options, forced_aligner=str(aligner_path or root / 'models/Qwen3-ForcedAligner-0.6B'),
        forced_aligner_kwargs=options, max_inference_batch_size=1, max_new_tokens=4096)


def transcribe(model, waveform, sample_rate, chunk_seconds=60, overlap_seconds=2,
               offset_seconds=0, progress=None):
    if not math.isfinite(offset_seconds) or offset_seconds < 0:
        raise ValueError('Offset must be finite and non-negative')
    chunks = []
    started = time.perf_counter()
    for plan in chunk_plan(len(waveform), sample_rate, chunk_seconds, overlap_seconds):
        output = model.transcribe(audio=(waveform[plan['input_start']:plan['input_end']], sample_rate),
                                  language='Chinese', context='', return_time_stamps=True)[0]
        items = list(output.time_stamps or [])
        chunk = owned_chunk(output.text, items, plan, sample_rate, offset_seconds)
        chunks.append(chunk)
        if progress:
            progress(chunks)
    chunks, cuts = stitch_chunks(chunks)
    return {'text': ''.join(chunk['text'] for chunk in chunks), 'chunks': chunks, 'seam_cuts': cuts,
            'words': [word for chunk in chunks for word in chunk['words']],
            'seams': seam_diagnostics(chunks), 'decode_seconds': time.perf_counter() - started,
            'profile': {'engine': 'Qwen3-ASR-0.6B', 'aligner': 'Qwen3-ForcedAligner-0.6B',
                        'language': 'Chinese', 'context': '', 'chunk_seconds': chunk_seconds,
                        'overlap_seconds': overlap_seconds, 'offset_seconds': offset_seconds,
                        'timestamp_kind': 'model_estimate_not_independent_timing_ground_truth',
                        'ownership': 'unique time-near shared adjacent pair; half-open midpoint fallback'}}
