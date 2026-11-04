"""Build a new allowlisted source candidate, never copy an installation wholesale."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tomllib

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'LICENSE_REVIEW.md', 'RELEASE_NOTES.md',
    'pyproject.toml', 'requirements-runtime-windows.txt', 'config.example.json',
    'bootstrap.ps1', 'run.ps1', 'scroll.ps1', 'tasks.ps1', 'launch.py', 'launch_mcp.py', 'launch_scroll.py', 'launch_tasks.py',
    'skill/SKILL.md', 'scroll-skill/SKILL.md',
    'docs/installation.md', 'docs/material-delivery.md', 'docs/material-reference.md', 'docs/reader-reference.md', 'docs/scroll-batch.md',
    'docs/tasks.md', 'docs/triage.md', 'docs/inbox-queue.md', 'docs/scroll-reference.md', 'docs/architecture.md',
    'CONTRIBUTING.md', 'examples/create_fixture.py',
    'tools/build_plugins.py', 'tools/build_candidate.py',
    'tools/build_dsh_index.py', 'discovery/dsh/index.json', 'discovery/dsh/README.md',
    'tools/build_mcpb.py', 'adapters/mcpb/README.md', 'adapters/mcpb/launch.py',
    'adapters/mcpb/reader/manifest.json', 'adapters/mcpb/scroll/manifest.json',
    'discovery/mcp/reader.server.json', 'discovery/mcp/scroll.server.json',
    'adapters/dsh/package.json', 'adapters/dsh/cordis.patch.yml',
    'adapters/dsh/locale/en.json', 'adapters/dsh/locale/zh.json',
    'adapters/dsh/README.md', 'adapters/dsh/LICENSE',
    'tools/check_models.py', 'docs/models/faster-whisper-medium.json',
    'licenses/upstream/watch-MIT.txt',
    'validation/release-20261104/report-source.md', 'validation/release-20261104/summary.json',
    'validation/mcp-registry-20261104/report-source.md', 'validation/mcp-registry-20261104/summary.json',
]


def build(destination, root=ROOT):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError('Candidate destination must not exist')
    if destination == root or root.is_relative_to(destination):
        raise ValueError('Candidate destination must not contain the source checkout')
    selected = {name: name for name in FILES}
    # Public operation references link to other top-level docs; keep those routes
    # available in the source archive without including runtime evidence/logs.
    for path in (root / 'docs').glob('*.md'):
        selected[path.relative_to(root).as_posix()] = path.relative_to(root).as_posix()
    for folder in ('video_reader', 'scroll_agent', 'reading_tasks', 'tests'):
        for path in (root / folder).rglob('*'):
            if path.is_file() and path.suffix in ('.py', '.json', '.txt', '.md') and '__pycache__' not in path.parts:
                selected[path.relative_to(root).as_posix()] = path.relative_to(root).as_posix()
    missing = [name for name in selected if not (root / name).is_file()]
    if missing:
        raise ValueError('Required candidate files missing: ' + ', '.join(missing))
    destination.mkdir(parents=True)
    manifest = {}
    for relative, target in sorted(selected.items()):
        original = root / relative
        output = destination / target
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, output)
        manifest[target] = hashlib.sha256(output.read_bytes()).hexdigest()
    (destination / '.gitignore').write_text('.venv/\n__pycache__/\n*.pyc\n*.egg-info/\nconfig.json\n.private/\ndata/\nauth/\nmodels/\nruntimes/\nresearch/\nintegrations/\n.test-work/\n', encoding='utf-8')
    for name in ('.gitignore',):
        manifest[name] = hashlib.sha256((destination / name).read_bytes()).hexdigest()
    version=tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8-sig'))['project']['version']
    report = {'version': version, 'files': manifest, 'publication': 'source_release_candidate',
              'original_code_license': 'MIT', 'credential_and_model_files_included': False}
    (destination / 'candidate-manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'candidate': str(destination), 'files': len(manifest), 'version': report['version']}


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(json.dumps(build(parser.parse_args().destination), ensure_ascii=False))
