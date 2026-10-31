"""Verify offline model files against a pinned, reviewed provenance inventory."""
import argparse
import hashlib
import json
from pathlib import Path


def check(manifest, directory):
    data = json.loads(Path(manifest).read_text(encoding='utf-8-sig'))
    root = Path(directory).resolve()
    results = []
    for item in data['files']:
        path = (root / item['name']).resolve()
        if not path.is_relative_to(root):
            raise ValueError('Model manifest path escapes the model directory')
        actual = None
        if path.is_file():
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        results.append({'name': item['name'], 'matches': actual == item['sha256']})
    return {'model': data.get('model'), 'revision': data.get('upstream_revision'),
            'complete': all(item['matches'] for item in results), 'files': results, 'network_used': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    result = check(args.manifest, args.directory)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result['complete'] else 1)
