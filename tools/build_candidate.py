"""Build a new allowlisted source candidate, never copy an installation wholesale."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    'pyproject.toml', 'requirements-runtime-windows.txt', 'config.example.json',
    'bootstrap.ps1', 'run.ps1', 'scroll.ps1', 'launch.py', 'launch_mcp.py', 'launch_scroll.py',
    'skill/SKILL.md', 'scroll-skill/SKILL.md',
    'docs/installation.md', 'docs/material-delivery.md', 'docs/scroll-batch.md',
    'CONTRIBUTING.md', 'examples/create_fixture.py',
    'tools/build_plugins.py', 'tools/build_candidate.py',
    'tools/check_models.py', 'docs/models/faster-whisper-medium.json',
    'licenses/upstream/watch-MIT.txt',
]


def build(destination, root=ROOT):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError('Candidate destination must not exist')
    if destination == root or root.is_relative_to(destination):
        raise ValueError('Candidate destination must not contain the source checkout')
    selected = {name: name for name in FILES}
    selected['README.candidate.md' if (root / 'README.candidate.md').is_file() else 'README.md'] = 'README.md'
    for folder in ('video_reader', 'scroll_agent', 'tests'):
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
    notices = ('# Distribution status and third-party notices\n\n'
        'Local technical candidate only. Original code has no selected public distribution license yet; do not infer permission to publish it.\n\n'
        'video_reader/vendor/{frames,runtime,transcribe,gemini}.py derives from watch 0.3.2 / bradautomates/claude-video, '
        'Copyright (c) 2026 Bradley Bonanno, MIT. Full notice: licenses/upstream/watch-MIT.txt.\n\n'
        'Python distributions retain their own installed licenses. yt-dlp is Unlicense; RapidOCR/PaddleOCR assets and optional Qwen models state Apache-2.0; '
        'Whisper model publishers state MIT. These dependencies/models are not bundled in this source archive. '
        'FFmpeg/ffprobe, Node and Python are separate machine dependencies. Review the actual binary build licenses when distributing binaries.\n\n'
        'No credentials, private configuration, model weights, user videos, research datasets, schedules or generated host paths are included.\n')
    (destination / 'THIRD_PARTY_NOTICES.md').write_text(notices, encoding='utf-8')
    for name in ('.gitignore', 'THIRD_PARTY_NOTICES.md'):
        manifest[name] = hashlib.sha256((destination / name).read_bytes()).hexdigest()
    report = {'version': '0.10.0rc4', 'files': manifest, 'publication': 'not_authorized',
              'original_code_license': 'pending_separate_decision', 'credential_and_model_files_included': False}
    (destination / 'candidate-manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return {'candidate': str(destination), 'files': len(manifest), 'version': report['version']}


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    print(json.dumps(build(parser.parse_args().destination), ensure_ascii=False))
