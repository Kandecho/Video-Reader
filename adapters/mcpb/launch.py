"""MCPB entry point that reuses one prepared local Video Reader installation."""
import os
from pathlib import Path
import runpy
import sys


def main():
    service = sys.argv[1:]
    if service not in (['reader'], ['scroll']):
        raise SystemExit('Expected MCPB service: reader or scroll')
    root_value = os.environ.get('VIDEO_READER_ROOT', '').strip()
    if not root_value:
        raise SystemExit('Select your prepared Video Reader installation in the bundle settings.')
    root = Path(root_value).resolve()
    entry = root / ('launch_mcp.py' if service == ['reader'] else 'launch_scroll.py')
    if not entry.is_file():
        raise SystemExit('Video Reader core entry point is missing. Prepare the core before enabling this bundle.')
    config_value = os.environ.get('VIDEO_READER_CONFIG', '').strip()
    config = Path(config_value).resolve() if config_value else root / 'config.json'
    if not config.is_file():
        raise SystemExit('Video Reader config is missing. Complete core setup or select an existing config file.')
    os.environ['VIDEO_READER_CONFIG'] = str(config)
    os.chdir(root)
    sys.argv = [str(entry)] + (['--mcp'] if service == ['scroll'] else [])
    runpy.run_path(str(entry), run_name='__main__')


if __name__ == '__main__':
    main()
