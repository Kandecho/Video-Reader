"""Standalone task interface; no Scroll import or login is needed for local queries."""
import argparse
import json
from video_reader.common import ReaderError
from video_reader.reader import Reader
from .api import ACTIONS, from_namespace


def task_options(parser):
    parser.add_argument('--task')
    parser.add_argument('--title',default='')
    parser.add_argument('--state')
    parser.add_argument('--priority',type=int)
    parser.add_argument('--reason',default='')
    parser.add_argument('--revision',type=int)
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--new-task',action='store_true')
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--complete',action='store_true')


def parser():
    p=argparse.ArgumentParser(description='Local reading queue, history, triage, results and batches')
    p.add_argument('--config')
    p.add_argument('action',choices=ACTIONS)
    p.add_argument('value',nargs='?',default='')
    p.add_argument('--query',default='')
    p.add_argument('--payload')
    p.add_argument('--offline',action='store_true')
    p.add_argument('--cursor')
    p.add_argument('--index',type=int)
    task_options(p)
    return p


def main():
    from video_reader.vendor.runtime import configure_stdio
    configure_stdio()
    args=parser().parse_args()
    try:
        print(json.dumps(from_namespace(Reader(args.config),args),ensure_ascii=False,allow_nan=False))
        return 0
    except (ReaderError,OSError,ValueError) as error:
        print(json.dumps({'status':'failed','error':str(error)},ensure_ascii=False))
        return 1
