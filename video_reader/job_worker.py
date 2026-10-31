"""Detached local Reader worker; no inherited MCP input/output pipes."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from video_reader.reader import Reader
from video_reader.jobs import Jobs, Running

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
        import time
        from video_reader.common import read_json, write_json
        path = Path(sys.argv[2]) / (sys.argv[3] + '.json')
        value = read_json(path)
        value.update(status='failed', stage='worker_start_failed', finished_at=time.time(),
                     error={'type': type(exc).__name__, 'message': str(exc)})
        write_json(path, value)
        raise SystemExit(1)
