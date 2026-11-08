"""Build local host adapters without bundling the shared Video Reader installation."""
import argparse
from video_reader.reading_policy import READING_POLICY
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.5.6'
MARKETPLACE = 'video-reader-local'
CORE_NOTICE = ("Use Video Reader MCP tools when connected. Otherwise use the prototype's `run.ps1` CLI. "
               "The prototype root is the parent directory of this `skill` directory.")
SCROLL_NOTICE = 'Use the Scroll Agent MCP for personal workflows. The shared installation is the parent of this skill directory.'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n' if isinstance(value, dict) else value
    path.write_text(text, encoding='utf-8')


def build(root=ROOT):
    root = Path(root).resolve()
    required = ['.venv/Scripts/python.exe', 'launch_mcp.py', 'launch_scroll.py', 'run.ps1', 'config.json', 'skill/SKILL.md', 'scroll-skill/SKILL.md']
    for relative in required:
        if not (root / relative).is_file():
            raise ValueError(f'Missing shared core file: {root / relative}')
    source = (root / 'skill/SKILL.md').read_text(encoding='utf-8')
    if source.count(CORE_NOTICE) != 1:
        raise ValueError('Canonical skill core-location paragraph changed; update the adapter renderer')
    location = (f"Use Video Reader MCP tools when connected. This thin plugin uses the shared core at `{root.as_posix()}`. "
                f"For CLI fallback run `& '{root.as_posix()}/run.ps1' ...` in PowerShell 7. "
                "The plugin/cache directory is NOT the core. All relative CLI examples below refer to the shared core directory. "
                "Never copy its models, runtime, auth or cache into this plugin. "
                "When continuing another chat, reuse its video URL/BV or session_id; saved evidence is shared, chat memory is not. "
                "Keep optional Qwen GPU decoding sequential across chats on this machine.")
    skill = source.replace(CORE_NOTICE, location)
    scroll_skill = (root / 'scroll-skill/SKILL.md').read_text(encoding='utf-8').replace(SCROLL_NOTICE,
        f'Use the Scroll Agent MCP for personal workflows. Shared installation: `{root.as_posix()}`. '
        f'CLI fallback: `& \'{root.as_posix()}/scroll.ps1\' ...` in PowerShell 7. Never infer the core from the plugin cache.')
    description = 'Video Reader is a reusable reading component; Scroll Agent adds personal feed, feedback and authorized delivery.'
    summary = {'version': VERSION, 'marketplace': MARKETPLACE, 'core_root': str(root), 'hosts': {}}
    for host in ('codex', 'claude'):
        marketplace_root = root / 'integrations' / host
        catalog_root = marketplace_root / '.agents/plugins' if host == 'codex' else marketplace_root
        plugin = marketplace_root / 'video-reader'
        server = {'command': str(root / '.venv/Scripts/python.exe'),
                  'args': ['-I', str(root / 'launch_mcp.py')],
                  'env': {'VIDEO_READER_CONFIG': str(root / 'config.json'), 'PYTHONIOENCODING': 'utf-8'}}
        server['tool_timeout_sec' if host == 'codex' else 'timeout'] = 3600 if host == 'codex' else 3600000
        manifest = {'name': 'video-reader', 'version': VERSION, 'description': description,
                    'author': {'name': 'Video Reader project'}}
        if host == 'codex':
            manifest.update(skills='./skills/', mcpServers='./.mcp.json',
                interface={'displayName': 'Video Reader / Scroll Agent', 'shortDescription': '通用读片组件与个人选片工作流'})
        write(plugin / f'.{host}-plugin/plugin.json', manifest)
        scroll_server = {**server, 'args': ['-I', str(root / 'launch_scroll.py'), '--mcp']}
        write(plugin / '.mcp.json', {'mcpServers': {'video-reader': server, 'scroll-agent': scroll_server}})
        if READING_POLICY not in skill:
            skill += '\n\n' + READING_POLICY + '\n'
        write(plugin / 'skills/video-read/SKILL.md', skill)
        write(plugin / 'skills/scroll-agent/SKILL.md', scroll_skill)
        write(plugin / 'README.md', f'# Video Reader {host} adapter {VERSION}\n\n'
              f'Thin local adapter for `{root.as_posix()}`.\n\n'
              'Two independent MCP servers and their scoped workflows are included: Video Reader and Scroll Agent. '
              'Models, Python environments, credentials and video/review caches remain in the shared core. '
              'This package is Windows-local, not a standalone portable application.\n\n'
              + (f"Register `{marketplace_root}` with `codex plugin marketplace add`, then run "
                 '`codex plugin add video-reader@video-reader-local`.\n' if host == 'codex' else
                 f"Register `{marketplace_root}` with `claude plugin marketplace add`, then run "
                 '`claude plugin install video-reader@video-reader-local`.\n'))
        if host == 'codex':
            catalog = catalog_root / 'marketplace.json'
            entry = {'name': 'video-reader', 'source': {'source': 'local', 'path': './video-reader'},
                     'policy': {'installation': 'AVAILABLE', 'authentication': 'ON_INSTALL'}, 'category': 'Productivity'}
            contents = {'name': MARKETPLACE, 'interface': {'displayName': 'Video Reader Local'}, 'plugins': [entry]}
        else:
            catalog = catalog_root / '.claude-plugin/marketplace.json'
            contents = {'name': MARKETPLACE, 'description': 'Local adapters for the shared Video Reader core',
                        'owner': {'name': 'Video Reader project'},
                        'plugins': [{'name': 'video-reader', 'source': './video-reader', 'description': description}]}
        write(catalog, contents)
        summary['hosts'][host] = {'marketplace_root': str(marketplace_root), 'catalog': str(catalog),
                                  'plugin_root': str(plugin), 'files': 5,
                                  'bytes': sum(path.stat().st_size for path in plugin.rglob('*') if path.is_file())}
    return summary


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core-root', type=Path, default=ROOT)
    arguments = parser.parse_args()
    print(json.dumps(build(arguments.core_root), ensure_ascii=False, indent=2))
