"""Public cache lookup. Callers never need to understand private manifest fields."""
from pathlib import Path
from urllib.parse import urlparse

from .common import read_json


def account_scope(config,source):
    host=(urlparse(source).hostname or '').lower()
    if host=='b23.tv' or host=='bilibili.com' or host.endswith('.bilibili.com'):
        from .bilibili_auth import BilibiliAuth
        return BilibiliAuth(config).account_scope()
    if host=='youtube.com' or host.endswith('.youtube.com') or host=='youtu.be':
        from .youtube_auth import account_scope as youtube_scope
        return youtube_scope(config['platforms']['youtube'])
    return None


def lookup(cache_dir,sources,*,scopes):
    result={source:[] for source in sources}
    if not cache_dir: return result
    for path in Path(cache_dir).glob('v_*/manifest.json'):
        try:
            data=read_json(path)
        except (OSError,ValueError):
            continue
        if not isinstance(data,dict): continue
        source=(data.get('source') or {}).get('canonical')
        if source not in result or data.get('native_only'): continue
        actual=(data.get('authentication') or {}).get('account_marker')
        if actual!=scopes.get(source): continue
        result[source].append({'session_id':data.get('id',path.parent.name),
            'media_available':bool(data.get('media_path') and Path(data['media_path']).is_file()),
            'account_scope':actual,'reading_completed':'not_inferred'})
    return result
