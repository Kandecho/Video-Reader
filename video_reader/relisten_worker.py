"""Private worker entry point; input is created by this component, not video content."""
import sys
from pathlib import Path

from .common import read_json, write_json
from .speech import decode


def main():
    path = Path(sys.argv[1])
    request = read_json(path)
    result = decode(request['data'], request['start'], request['end'], path.parent,
                    request['config'], request['context'], lambda s: print(s, flush=True),
                    precise_words=request['precise_words'], terms=request['terms'])
    write_json(path.parent / 'decoded.json', result)


if __name__ == '__main__':
    main()
