"""Detached local Reader worker; no inherited MCP input/output pipes."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_reader.reader import Reader
from video_reader.jobs import Jobs, Running


def fail_startup(root, job_id, error):
    import time
    from filelock import FileLock
    from video_reader.common import read_json, write_json
    root = Path(root)
    with FileLock(str(root / (job_id + '.status.lock')), timeout=10):
        path = root / (job_id + '.json')
        value = read_json(path)
        value.update(status='failed', stage='worker_start_failed', finished_at=time.time(),
                     error={'type': type(error).__name__, 'message': str(error)})
        write_json(path, value)

if __name__ == '__main__':
    from video_reader.vendor.runtime import configure_stdio
    configure_stdio()
    try:
        reader = Reader(sys.argv[1])
        store = Jobs(reader)
        if store.root.resolve() != Path(sys.argv[2]).resolve():
            raise ValueError('Worker config cache does not match the requested job store')
        Running(store, sys.argv[3]).run()
    except Exception as exc:
        fail_startup(sys.argv[2], sys.argv[3], exc)
        raise SystemExit(1)
