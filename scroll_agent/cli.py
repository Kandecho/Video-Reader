"""CLI control for explicit one-shot work and opt-in wake polling."""
import copy
import math
import os
from pathlib import Path
import sys
import time

from .agent import Agent, validate
from video_reader.common import ROOT, ReaderError, configuration_path, merge, read_json, settings, write_json
from video_reader.preview import candidates, preview


def configure(config_path, payload):
    if not isinstance(payload, dict):
        raise ReaderError('Agent configuration must be a JSON object')
    current = settings(config_path)
    def check_keys(value, template):
        for key in value:
            if key not in template:
                raise ReaderError('Unknown agent setting: ' + key)
            if isinstance(template[key], dict):
                if not isinstance(value[key], dict):
                    raise ReaderError('Nested settings must be JSON objects')
                check_keys(value[key], template[key])
    check_keys(payload, current['agent'])
    candidate = merge(copy.deepcopy(current['agent']), payload)
    validate(candidate)
    path = configuration_path(config_path)
    saved = read_json(path) if path.is_file() else {}
    saved['agent'] = merge(saved.get('agent', {}), payload)
    write_json(path, saved)
    return {'updated': True, 'settings': candidate, 'automatic_task_created': False}


def dispatch(reader, args):
    if args.action.startswith('batch-'):
        from .batch import Batch
        batch = Batch(reader, offline=args.offline)
        if args.action == 'batch-start':
            if not args.payload:
                raise ReaderError('batch-start requires --payload with sources, optional task/source')
            return batch.start(**read_json(args.payload))
        if args.action == 'batch-next':
            return batch.next(args.value, args.cursor)
        if args.action == 'batch-retry':
            return batch.retry(args.value, args.index)
        return batch.status(args.value)
    if args.action == 'config':
        if not args.payload:
            return {'settings': reader.config['agent']}
        return configure(args.config, read_json(args.payload))
    agent = Agent(reader, offline=args.offline)
    if args.action == 'status':
        return agent.status()
    if args.action == 'resume':
        return agent.platform.resume()
    if args.action == 'candidates':
        return {'items': candidates(agent.platform, args.query or args.value, agent.options['candidate_count']),
                'notice': 'Candidate metadata only; no video has been read'}
    if args.action == 'preview':
        return preview(agent.platform, args.value)
    if args.action == 'prepare':
        return agent.prepare(args.query or args.value)
    if args.action == 'finish':
        if not args.payload:
            raise ReaderError('finish requires a decision JSON file')
        return agent.finish(args.value, read_json(args.payload), dry_run=not args.deliver)
    if args.action == 'run':
        return agent.run(args.query or args.value, dry_run=not args.deliver)
    if args.action == 'daily':
        if args.scheduled and not agent.options['daily']['enabled']:
            return {'status': 'daily_disabled'}
        return agent.run(dry_run=not args.deliver, daily=True)
    if args.action == 'deliver':
        return agent.deliver(args.value)
    if args.action == 'test-message':
        return agent.test_message(confirm=args.confirm)
    if args.action == 'memory':
        if args.payload:
            data = read_json(args.payload)
            return agent.memory.remember(data['text'], data.get('kind', args.kind), data.get('source', args.source))
        if args.value:
            return agent.memory.remember(args.value, args.kind, args.source)
        return {'items': agent.memory.recall(args.query)}
    if args.action == 'forget':
        return agent.memory.forget(int(args.value))
    if args.action == 'tick':
        return agent.tick(args.query or args.value)
    if not math.isfinite(args.poll_seconds) or args.poll_seconds < 1:
        raise ReaderError('poll-seconds must be at least one second')
    if not agent.options['wake']['enabled']:
        return {'status': 'disabled', 'watch_started': False}
    try:
        while True:
            active = Agent(type(reader)(args.config), offline=args.offline)
            if not active.options['wake']['enabled']:
                return {'status': 'disabled', 'watch_stopped': True}
            try:
                active.tick(args.query or args.value)
            except (ReaderError, OSError) as error:
                print(f'Video agent wake stopped this round: {error}', file=sys.stderr, flush=True)
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        return {'status': 'watch_stopped'}


def main():
    from video_reader.vendor.runtime import configure_stdio
    configure_stdio()
    import argparse
    import json
    from video_reader.reader import Reader
    parser = argparse.ArgumentParser(description='Scroll Agent: personal video workflows using Video Reader')
    parser.add_argument('--config')
    parser.add_argument('action', choices=('status', 'config', 'candidates', 'preview', 'prepare', 'finish',
                        'run', 'daily', 'deliver', 'test-message', 'memory', 'forget', 'tick', 'watch', 'resume',
                        'batch-start', 'batch-next', 'batch-status', 'batch-retry'))
    parser.add_argument('value', nargs='?', default='')
    parser.add_argument('--query', default='')
    parser.add_argument('--payload')
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--deliver', action='store_true')
    parser.add_argument('--scheduled', action='store_true')
    parser.add_argument('--confirm', action='store_true')
    parser.add_argument('--kind', choices=('preference', 'feedback', 'observation'), default='observation')
    parser.add_argument('--source', default='')
    parser.add_argument('--poll-seconds', type=float, default=30)
    parser.add_argument('--cursor')
    parser.add_argument('--index', type=int)
    args = parser.parse_args()
    try:
        result = dispatch(Reader(args.config), args)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        if result.get('status') in ('failed', 'acquisition_failed') or result.get('delivery', {}).get('status') in ('rejected', 'uncertain'):
            return 1
        return 0
    except (ReaderError, OSError, ValueError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=False))
        return 1
