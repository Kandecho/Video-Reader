import os
import sys
from pathlib import Path

from .common import ROOT, read_json, write_json
from .qwen_pipeline import load_model, owned_chunk

def main():
    import soundfile
    request_path = Path(sys.argv[1])
    request = read_json(request_path)
    waveform, sample_rate = soundfile.read(request['audio'], dtype='float32')
    options = request['options']
    os.environ['NUMBA_CACHE_DIR'] = options.get('cache_dir', str(request_path.parent / 'numba-cache'))
    model = load_model(ROOT, options['model_path'], options['aligner_path'])
    output = model.transcribe(audio=(waveform, sample_rate), language='Chinese',
                              context=request['context'], return_time_stamps=True)[0]
    plan = {'index': 0, 'owner_start': round((request['start'] - request['audio_start']) * sample_rate),
            'owner_end': min(len(waveform), round((request['end'] - request['audio_start']) * sample_rate)),
            'input_start': 0, 'input_end': len(waveform)}
    chunk = owned_chunk(output.text, list(output.time_stamps or []), plan, sample_rate, request['audio_start'])
    write_json(request_path.with_name('decoded.json'), chunk)


if __name__ == '__main__':
    main()
