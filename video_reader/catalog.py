"""Public cache lookup. Callers never need to understand private manifest fields."""
from pathlib import Path
import hashlib
from urllib.parse import urlparse

from .common import read_json


def account_scope(config,source):
    host=(urlparse(source).hostname or '').lower()
    if host=='b23.tv' or host=='bilibili.com' or host.endswith('.bilibili.com'):
        auth=config.get('bilibili_auth') or {}
        credential=Path(auth.get('directory',''))/'credential.json'
        if auth.get('enabled') and credential.is_file():
            try:
                return read_json(credential).get('account_marker')
            except (OSError,ValueError):
                return None
        return None
    if host=='youtube.com' or host.endswith('.youtube.com') or host=='youtu.be':
        cookie=config['platforms']['youtube'].get('cookies_file')
        if cookie and Path(cookie).is_file():
            return 'youtube-'+hashlib.sha256(Path(cookie).read_bytes()).hexdigest()[:24]
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
