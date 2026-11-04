"""One page of an uploader's works using the pinned yt-dlp extractor and managed transport."""
import math
import re
import time
from types import MethodType
from urllib.parse import urlencode, urlparse
from yt_dlp.utils import ExtractorError

from .common import ReaderError, UNTRUSTED, read_json, write_json
from .discovery import _candidate
from .platform import PlatformError
from .sources import resolve


def target(source, platform=None):
    if not isinstance(source, str) or not source.strip():
        raise ReaderError('Uploader source must be a UID, Bilibili space URL, or BV/video URL')
    value = source.strip()
    if re.fullmatch(r'[1-9]\d{0,19}', value):
        return {'uid': value}
    match = re.fullmatch(r'https?://space\.bilibili\.com/([1-9]\d{0,19})(?:/(?:upload/)?video)?/?(?:[?#].*)?', value)
    if match:
        return {'uid': match[1]}
    video = resolve(value, shortlink_resolver=platform.resolve_shortlink if platform else None)
    if video['platform'] != 'bilibili':
        raise ReaderError('Uploader enumeration currently supports Bilibili only')
    return {'shortlink': video['canonical']} if video.get('shortlink') else {'bvid': video['bvid']}


class _QuietLogger:
    def debug(self, message):
        pass
    def warning(self, message):
        pass
    def error(self, message):
        pass


def _page(platform, uid, page):
    """Keep yt-dlp's signing/paging, route all JSON through shared auth/cache/budget."""
    from yt_dlp import YoutubeDL
    from yt_dlp.extractor.bilibili import BilibiliSpaceVideoIE
    from .bilibili_auth import USER_AGENT
    pages = {}
    ttl = platform.config['preview']['recommendation_ttl_seconds']
    options = {'quiet': True, 'no_warnings': True, 'logger': _QuietLogger(), 'cachedir': False,
               'extract_flat': True, 'skip_download': True, 'retries': 0, 'extractor_retries': 0,
               'http_headers': {'User-Agent': USER_AGENT}}
    with YoutubeDL(options) as downloader:
        for cookie in platform.jar:
            downloader.cookiejar.set_cookie(cookie)
        extractor = BilibiliSpaceVideoIE(downloader)

        def fetch(self, url, video_id, *args, **kwargs):
            parsed = urlparse(url)
            if parsed.hostname != 'api.bilibili.com' or parsed.path not in ('/x/web-interface/nav', '/x/space/wbi/arc/search'):
                raise ReaderError('Uploader backend requested an unexpected endpoint')
            query = kwargs.get('query') or {}
            address = url + ('?' + urlencode(query) if query else '')
            data = platform.request(address, ttl=30 if parsed.path.endswith('/nav') else ttl,
                                    headers=kwargs.get('headers'))
            if parsed.path.endswith('/arc/search'):
                pages[int(query['pn'])] = data['data']
            return data

        extractor._download_json = MethodType(fetch, extractor)
        # This small adapter deliberately targets the project's pinned yt-dlp version.
        playlist = extractor._real_extract(f'https://space.bilibili.com/{uid}/video')
        first = pages[1]
        size, total = int(first['page']['ps']), int(first['page']['count'])
        if size <= 0 or total < 0:
            raise ReaderError('Uploader backend returned invalid pagination')
        if page > max(1, math.ceil(total / size)):
            raise ReaderError('Uploader page is outside the reported range')
        entries = playlist['entries'].getpage(page - 1)
    raw = {str(row.get('bvid')): row for row in (pages.get(page, {}).get('list') or {}).get('vlist', [])}
    items, seen = [], set()
    for entry in entries:
        row = raw.get(str(entry.get('id')), {})
        if re.fullmatch(r'BV[a-zA-Z0-9]{10}', str(entry.get('id', ''))):
            item = _candidate({**row, 'bvid': entry['id'], 'mid': uid,
                               'duration': row.get('length', row.get('duration')), 'pubdate': row.get('created', row.get('pubdate'))})
            item['kind'] = 'video'
        else:
            item = {'kind': 'collection', 'id': entry.get('id'), 'url': entry.get('url'),
                    'title': entry.get('title'), 'uploader_id': uid, 'uploader_url': f'https://space.bilibili.com/{uid}',
                    'reading_status': 'not_assessed'}
        identity = item.get('bvid') or item.get('id') or item.get('url')
        if identity not in seen:
            seen.add(identity)
            items.append(item)
    name = next((row.get('author') for row in raw.values() if row.get('author')), None)
    expected = max(0, min(size, total - (page - 1) * size))
    complete = len(entries) == expected
    return {'items': items, 'uploader': name, 'page_size': size, 'reported_total': total,
            'total_pages': math.ceil(total / size), 'page_complete': complete,
            'collection_complete': page == 1 and complete and len(items) == total,
            'duplicates_removed': len(entries) - len(items),
            'next_page': page if not complete else page + 1 if page * size < total else None,
            'status': 'ready' if complete else 'partial'}


def uploader_videos(platform, source, page=1):
    selected = target(source, platform)
    if isinstance(page, bool) or not isinstance(page, int) or not 1 <= page <= 1000:
        raise ReaderError('page must be an integer between 1 and 1000')
    ttl = platform.config['preview']['recommendation_ttl_seconds']
    owner = {}
    if 'bvid' in selected:
        info = platform.json('/x/web-interface/view', {'bvid': selected['bvid']}, ttl=platform.config['preview']['material_ttl_seconds'])
        owner = info.get('owner') or {}
        if not owner.get('mid'):
            raise ReaderError('Video metadata does not identify its uploader')
        selected['uid'] = str(owner['mid'])
    uid = selected['uid']
    manifest = platform.root / f'uploader-{uid}-page-{page}.json'
    if manifest.is_file() and (platform.offline or time.time() - manifest.stat().st_mtime <= ttl):
        result = read_json(manifest)
        return {**result, 'cache': 'hit'}
    base = {'uploader_id': uid, 'uploader_url': f'https://space.bilibili.com/{uid}', 'uploader': owner.get('name'),
            'page': page, 'items': [], 'page_complete': False, 'collection_complete': False,
            'next_page': page, 'material_level': 'metadata', 'reading_status': 'not_assessed', 'notice': UNTRUSTED}
    try:
        result = {**base, **_page(platform, uid, page), 'cache': 'miss', 'fetched_at': time.time()}
        result['uploader'] = owner.get('name') or result.get('uploader')
    except PlatformError as error:
        return {**base, 'status': 'blocked' if 'paused' in error.code or 'code:-' in error.code or 'http_' in error.code else 'failed',
                'error': {'code': error.code, 'message': str(error)}}
    except (ReaderError, ExtractorError, OSError, KeyError, TypeError, ValueError) as error:
        message = re.sub(r'https?://[^\s]+', '[url]', str(error))
        return {**base, 'status': 'failed', 'error': {'code': 'uploader_backend_error', 'message': message}}
    write_json(manifest, result)
    return result
