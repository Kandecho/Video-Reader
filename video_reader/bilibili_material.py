"""Bilibili caption protocol shared by full acquisition and light previews."""
from urllib.parse import urlencode


API = 'https://api.bilibili.com'


def caption_kind(track):
    """AI originals can have ai_type=0; ai-* still identifies an AI track."""
    return 'automatic' if track.get('ai_type') or str(track.get('lan', '')).startswith('ai-') else 'manual'


def captions(request, bvid, cid, language='auto', *, strict=False):
    """Translate one caption track; callers retain their own coverage policy."""
    player = request(API + '/x/player/wbi/v2?' + urlencode({'bvid': bvid, 'cid': cid}))
    data = player.get('data') or {}
    tracks = (data.get('subtitle') or {}).get('subtitles') or []
    code = player.get('code')
    login_required = code == -101 or data.get('need_login_subtitle') and not tracks
    state = {'status': 'login_required' if login_required else 'unavailable'}
    if code not in (None, 0):
        state['code'] = code
    if login_required:
        state['requires_login'] = True
    if language != 'auto':
        tracks = [track for track in tracks if track.get('lan') == language]
    if not tracks:
        return state
    chosen = min(tracks, key=lambda track: (
        not track.get('lan', '').startswith(('zh', 'ai-zh')), caption_kind(track) == 'automatic'))
    url = chosen['subtitle_url']
    raw = request('https:' + url if url.startswith('//') else url)
    body = raw['body'] if strict else raw.get('body', [])
    return {**state, 'status': 'ready',
            'segments': [{'start': item['from'], 'end': item['to'], 'text': item['content']} for item in body],
            'track': {'kind': caption_kind(chosen), 'language': chosen.get('lan'), 'source': 'bilibili', 'cid': cid}}
