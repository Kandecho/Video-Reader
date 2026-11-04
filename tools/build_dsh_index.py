"""Build the author's DSH index from one immutable, already released adapter commit."""
import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'adapters/dsh'
REPOSITORY = 'https://github.com/Kandecho/Video-Reader'
SEARCH_TERMS = ['transcript', 'subtitles', 'frames', 'inbox', '字幕', '画面']


def build(commit, root=ROOT):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Use the full immutable release commit, not a branch or abbreviated SHA')

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root).decode('utf-8')

    def read(name):
        return json.loads(git('show', f'{commit}:{PACKAGE}/{name}'))

    manifest = read('package.json')
    version = manifest['version']
    if manifest.get('private') or not manifest.get('dsh', {}).get('bundle', {}).get('patch'):
        raise ValueError('The selected commit must contain a public DSH bundle')
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', version):
        raise ValueError('Adapter version must be SemVer')
    title, description = {}, {}
    for language in ('en', 'zh'):
        meta = read(f'locale/{language}.json')['meta']
        title[language] = meta['title']
        description[language] = meta['description']
    if manifest.get('os') == ['win32']:
        description['en'] = 'Windows. ' + description['en']
        description['zh'] = 'Windows。' + description['zh']
    keywords = list(dict.fromkeys([*manifest.get('keywords', []), *SEARCH_TERMS]))
    return {
        'format': 1,
        'title': {'en': 'Video Reader — publisher index', 'zh': 'Video Reader 项目索引'},
        'description': {'en': 'Maintained by the Video Reader author. Reader, shared tasks and Scroll are shipped together.',
                        'zh': '项目作者维护的索引，整包包含 Reader、通用任务和 Scroll。'},
        'plugins': [{
            'name': manifest['name'], 'title': title, 'description': description,
            'author': manifest['author'], 'homepage': manifest['homepage'],
            'repository': {'url': REPOSITORY, 'directory': PACKAGE},
            'metadata': {'keywords': keywords},
            'versions': [{'version': version,
                          'publishTimestamp': int(git('show', '-s', '--format=%ct', commit).strip()),
                          'source': {'type': 'git', 'url': REPOSITORY, 'commit': commit, 'path': PACKAGE},
                          'engines': {'dsh': manifest['engines']['dsh']}}],
        }],
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'discovery/dsh/index.json')
    parser.add_argument('--check', action='store_true', help='Fail if the published file differs; do not write')
    options = parser.parse_args()
    content = json.dumps(build(options.commit), ensure_ascii=False, indent=2) + '\n'
    if options.check:
        if options.output.read_text(encoding='utf-8') != content:
            raise SystemExit('Index differs from the selected release; regenerate before publishing')
    else:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(content, encoding='utf-8')
    print(f'{"Checked" if options.check else "Built"} {options.output}')
