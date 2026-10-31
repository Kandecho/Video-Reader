"""Bilibili candidate discovery without downloading or claiming to have read videos."""
from __future__ import annotations

import html
import hashlib
import http.cookiejar
import math
import re
import time
from urllib.parse import urlencode, urlparse

from .bilibili_auth import BiliSession, BilibiliAuth, NAV, _cookie, _cookies, _cookie_value
from .common import ReaderError, UNTRUSTED, read_json

ORDERS = {'relevance': 'totalrank', 'views': 'click', 'newest': 'pubdate'}
WBI_INDICES = (46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
               27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13)


def _search_params(session, params):
    if not _cookie_value(session.jar, 'buvid3'):
        fingerprint = session.request('https://api.bilibili.com/x/frontend/finger/spi')
        device = fingerprint.get('data') or {}
        if fingerprint.get('code') != 0 or not device.get('b_3'):
            raise ReaderError('Bilibili search device initialization failed')
        for key, name in (('b_3', 'buvid3'), ('b_4', 'buvid4')):
            if device.get(key):
                session.jar.set_cookie(_cookie(name, device[key]))
    nav = session.request(NAV)
    try:
        images = nav['data']['wbi_img']
        lookup = ''.join(urlparse(images[key]).path.rsplit('/', 1)[-1].split('.')[0]
                         for key in ('img_url', 'sub_url'))
        salt = ''.join(lookup[index] for index in WBI_INDICES)
    except (KeyError, TypeError, IndexError):
        raise ReaderError('Bilibili search signing keys unavailable') from None
    signed = {key: str(value).translate(str.maketrans('', '', "!'()*"))
              for key, value in sorted({**params, 'wts': int(time.time())}.items())}
    signed['w_rid'] = hashlib.md5((urlencode(signed) + salt).encode()).hexdigest()
    return signed


def _integer(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ReaderError(f'{name} must be an integer between {minimum} and {maximum}')


def _duration(value):
    try:
        if isinstance(value, str):
            parts = value.split(':')
            return sum(float(part) * 60 ** index for index, part in enumerate(reversed(parts)))
        return float(value)
    except (TypeError, ValueError):
        return None


def _text(value):
    return html.unescape(re.sub(r'<[^>]*>', '', str(value or ''))).strip()


def _cached_videos(cache):
    cached = set()
    for path in cache.glob('v_*/manifest.json'):
        try:
            source = read_json(path).get('source', {})
            if source.get('platform') == 'bilibili' and source.get('bvid'):
                cached.add(source['bvid'])
        except (OSError, ValueError, AttributeError):
            continue
    return cached


def _candidate(item):
    bvid = item.get('bvid')
    if not isinstance(bvid, str) or not re.fullmatch(r'BV[a-zA-Z0-9]{10}', bvid):
        return None
    owner = item.get('owner') or {}
    stats = item.get('stat') or {}
    duration = _duration(item.get('duration'))
    if duration is not None and (not math.isfinite(duration) or duration < 0):
        duration = None
    return {'bvid': bvid, 'url': f'https://www.bilibili.com/video/{bvid}?p=1',
            'title': _text(item.get('title')), 'description': _text(item.get('description', item.get('desc'))),
            'uploader': _text(item.get('author', owner.get('name'))),
            'uploader_id': str(item.get('mid') or owner.get('mid') or '') or None,
            'uploader_url': f"https://space.bilibili.com/{item.get('mid') or owner.get('mid')}" if item.get('mid') or owner.get('mid') else None,
            'duration_seconds': duration, 'published_at': item.get('pubdate'),
            'view_count': item.get('play', stats.get('view')),
            'category': _text(item.get('typename', item.get('tname'))),
            'part_count': item.get('videos'), 'reading_status': 'not_assessed'}


def discover(reader, query=None, *, page=1, page_size=10, order='relevance',
             min_duration=0, max_duration=None, exclude_cached=True):
    _integer(page, 'page', 1, 1000)
    _integer(page_size, 'page_size', 1, 50)
    if order not in ORDERS:
        raise ReaderError('order must be relevance, views or newest')
    if query is not None and (not isinstance(query, str) or not 1 <= len(query.strip()) <= 200):
        raise ReaderError('query must contain 1..200 characters; use discover for popular videos')
    if not isinstance(exclude_cached, bool):
        raise ReaderError('exclude_cached must be true or false')
    for name, value in (('min_duration', min_duration), ('max_duration', max_duration)):
        if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))
                                  or not math.isfinite(value) or value < 0):
            raise ReaderError(f'{name} must be finite nonnegative seconds')
    if min_duration is None or (max_duration is not None and min_duration > max_duration):
        raise ReaderError('min_duration must not exceed max_duration')
    mode = 'search' if query is not None else 'popular'
    if mode == 'popular' and order != 'relevance':
        raise ReaderError('popular discovery uses platform order; order applies only to search')
    query = query.strip() if query is not None else None
    params = ({'search_type': 'video', 'keyword': query, 'page': page, 'page_size': page_size,
               'order': ORDERS[order]} if query is not None else {'pn': page, 'ps': page_size})
    endpoint = 'wbi/search/type' if query is not None else 'popular'
    profile = reader.config['platforms']['bilibili']
    with BilibiliAuth(reader.config).reader_profile(profile) as (io_profile, scope, authentication):
        jar = http.cookiejar.MozillaCookieJar()
        if io_profile.get('cookies_file'):
            jar.load(io_profile['cookies_file'], ignore_discard=True, ignore_expires=False)
        session = BiliSession(_cookies(jar))
        if query is not None:
            params = _search_params(session, params)
        response = session.request(
            'https://api.bilibili.com/x/web-interface/' + endpoint + '?' + urlencode(params))
    if not isinstance(response, dict) or response.get('code') != 0:
        code = response.get('code') if isinstance(response, dict) else None
        raise ReaderError(f'Bilibili {mode} returned code {code}; no candidates were retrieved')
    data = response.get('data')
    key = 'result' if query is not None else 'list'
    if not isinstance(data, dict) or not isinstance(data.get(key, []), list):
        raise ReaderError(f'Bilibili {mode} returned invalid candidate data')
    raw_items = data.get(key, [])
    cached = _cached_videos(reader.cache)
    items, seen = [], set()
    excluded = {'duplicate': 0, 'cached': 0, 'duration': 0, 'invalid': 0}
    for raw_item in raw_items:
        item = _candidate(raw_item) if isinstance(raw_item, dict) else None
        if item is None:
            excluded['invalid'] += 1
            continue
        bvid = item['bvid']
        if bvid in seen:
            excluded['duplicate'] += 1
            continue
        seen.add(bvid)
        item['cached'] = bvid in cached
        if exclude_cached and item['cached']:
            excluded['cached'] += 1
            continue
        duration = item['duration_seconds']
        filtered = min_duration > 0 or max_duration is not None
        if filtered and (duration is None or duration < min_duration
                         or (max_duration is not None and duration > max_duration)):
            excluded['duration'] += 1
            continue
        items.append(item)
    if query is not None:
        try:
            more = page < int(data['numPages'])
        except (KeyError, TypeError, ValueError):
            raise ReaderError('Bilibili search did not return valid pagination') from None
    else:
        if 'no_more' not in data:
            raise ReaderError('Bilibili popular did not return pagination')
        more = not data['no_more']
    return {'platform': 'bilibili', 'mode': mode, 'query': query, 'order': order,
            'page': page, 'page_size': page_size, 'next_page': page + 1 if more and page < 1000 else None,
            'total_results': data.get('numResults'), 'fetched_at': time.time(),
            'filters': {'min_duration': min_duration, 'max_duration': max_duration, 'exclude_cached': exclude_cached},
            'items': items, 'returned_count': len(items), 'platform_count': len(raw_items), 'excluded': excluded,
            'authentication': authentication,
            'notice': 'Metadata only. Cached does not mean read. Filters apply to this platform page; '
                      'an empty filtered page may still have next_page. Choose a candidate URL and call video_open. ' + UNTRUSTED}
