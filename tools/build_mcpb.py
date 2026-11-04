"""Build two thin MCP bundles, without copying a local runtime or user state."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(destination, root=ROOT):
    destination, root = Path(destination).resolve(), Path(root).resolve()
    if destination.exists():
        raise ValueError('MCPB destination must not exist')
    if destination == root or root.is_relative_to(destination):
        raise ValueError('MCPB destination must not contain the source checkout')
    destination.mkdir(parents=True)
    artifacts = []
    for service in ('reader', 'scroll'):
        manifest_path = root / 'adapters/mcpb' / service / 'manifest.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        members = {
            'manifest.json': manifest_path,
            'server/launch.py': root / 'adapters/mcpb/launch.py',
            'README.md': root / 'adapters/mcpb/README.md',
            'LICENSE': root / 'LICENSE',
        }
        archive = destination / f'{manifest["name"]}-{manifest["version"]}.mcpb'
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for name, path in sorted(members.items()):
                info = zipfile.ZipInfo(name, date_time=(2026, 11, 4, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                bundle.writestr(info, path.read_bytes())
        artifacts.append({'service': service, 'filename': archive.name,
                          'sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                          'bytes': archive.stat().st_size, 'files': sorted(members)})
    return artifacts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(json.dumps(build(parser.parse_args().destination), indent=2))
