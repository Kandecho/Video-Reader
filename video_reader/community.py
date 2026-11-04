"""Read-only Bilibili comments and current segmented danmaku through managed transport."""
import re
from urllib.parse import urlencode

from .common import ReaderError, UNTRUSTED, digest, read_json, write_json
from .platform import API, PlatformError
from .sources import resolve


def integer(value, name, low=1, high=1000000):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ReaderError(f'{name} must be an integer between {low} and {high}')
    return value


def controls(source, page=1, page_size=20, sort='newest', root=None):
    video(source)
    integer(page, 'page')
    integer(page_size, 'page_size', high=20)
    if sort not in ('newest', 'likes', 'replies'):
        raise ReaderError('sort must be newest, likes or replies')
    if root is not None and (not isinstance(root, str) or not re.fullmatch(r'[1-9]\d{0,19}', root)):
        raise ReaderError('root must be a positive comment ID string')


def video(source, platform=None):
    if not isinstance(source, str) or not source.strip():
        raise ReaderError('source must be a Bilibili BV or video URL')
    selected = resolve(source, shortlink_resolver=platform.resolve_shortlink if platform else None)
    if selected['platform'] != 'bilibili':
        raise ReaderError('Community reading currently supports Bilibili only')
    return selected


def metadata(platform, source):
    selected = video(source, platform)
    info = platform.json('/x/web-interface/view', {'bvid': selected['bvid']}, ttl=platform.config['preview']['material_ttl_seconds'])
    return selected, info


def failure(base, error):
    code = error.code
    blocked = any(word in code for word in ('paused', 'budget', 'login', 'platform_code:', 'platform_http_'))
    return {**base, 'status': 'blocked' if blocked else 'failed', 'error': {'code': code}}


def comment(item, *, children=True):
    if not isinstance(item, dict) or not item.get('rpid'):
        raise ReaderError('platform_invalid_comment')
    content, member = item.get('content') or {}, item.get('member') or {}
    result = {'id': str(item['rpid']), 'root_id': str(item.get('root') or 0),
              'parent_id': str(item.get('parent') or 0), 'text': content.get('message', ''),
              'created_at': item.get('ctime'), 'likes': item.get('like'),
              'author': {'id': str(member.get('mid') or item.get('mid') or ''), 'name': member.get('uname')},
              'reply_count': item.get('rcount', item.get('count', 0)),
              'pictures': content.get('pictures') or []}
    if children:
        result['reply_preview'] = [comment(row, children=False) for row in item.get('replies') or []]
        result['replies_complete'] = result['reply_count'] == 0
        result['replies_hint'] = {'root': result['id'], 'page': 1} if result['reply_count'] else None
    return result


def comments(platform, source, page=1, page_size=20, sort='newest', root=None):
    controls(source, page, page_size, sort, root)
    base = {'material_level': 'comments', 'source': source, 'page': page, 'page_size': page_size,
            'sort': 'thread_order' if root else sort, 'root': root, 'items': [], 'pinned': [],
            'page_complete': False, 'collection_complete': False, 'next_page': page,
            'is_full_population': False, 'notice': UNTRUSTED,
            'coverage_note': 'Current account-visible comments only. Deleted, hidden and historical comments are not guaranteed; inline replies are previews.'}
    try:
        selected, info = metadata(platform, source)
        base.update(bvid=selected['bvid'], aid=str(info['aid']), comments_scope='video_all_parts')
        params = {'type': 1, 'oid': info['aid'], 'pn': page, 'ps': page_size}
        if root:
            params['root'] = root
        else:
            params.update(sort={'newest': 0, 'likes': 1, 'replies': 2}[sort], nohot=1)
        data = platform.json('/x/v2/reply/reply' if root else '/x/v2/reply', params, ttl=600)
        paging = data.get('page') or {}
        total = paging.get('count')
        size = paging.get('size')
        if (isinstance(total, bool) or not isinstance(total, int) or total < 0 or
                isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 20 or paging.get('num') != page):
            raise ReaderError('platform_invalid_comment_page')
        rows = data.get('replies') or []
        items = [comment(row, children=not root) for row in rows]
        unique = {item['id']: item for item in items}
        expected = max(0, min(size, total - (page - 1) * size))
        complete = len(rows) == expected and len(unique) == len(rows)
        upper = (data.get('upper') or {}).get('top')
        pins = [upper] if isinstance(upper, dict) else []
        pins += [row for row in (data.get('top_replies') or []) if isinstance(row, dict)]
        if isinstance(data.get('top'), dict):
            pins += [row for row in data['top'].values() if isinstance(row, dict) and row.get('rpid')]
        pinned = list({str(row['rpid']): comment(row) for row in pins if row.get('rpid')}.values())
        return {**base, 'items': list(unique.values()), 'pinned': pinned,
                'thread_root': comment(data['root'], children=False) if isinstance(data.get('root'), dict) else None,
                'reported_total': total, 'reported_total_with_replies': paging.get('acount'),
                'page_size': size, 'page_complete': complete,
                'collection_scope': 'thread_replies' if root else 'top_level_comments',
                'collection_complete': page == 1 and complete and len(unique) == total,
                'retry_page': page if not complete else None,
                'next_page': page + 1 if page * size < total else None,
                'status': 'ready' if complete else 'partial'}
    except PlatformError as error:
        return failure(base, error)


def varint(blob, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(blob):
            break
        byte = blob[offset]
        offset += 1
        if shift == 63 and byte > 1:
            break
        value |= (byte & 127) << shift
        if byte < 128:
            return value, offset
    raise ReaderError('platform_invalid_protobuf_varint')


def fields(blob):
    """Decode wire values; skip unknown fields without depending on a protobuf runtime."""
    offset = 0
    while offset < len(blob):
        tag, offset = varint(blob, offset)
        number, wire = tag >> 3, tag & 7
        if not number:
            raise ReaderError('platform_invalid_protobuf_field')
        if wire == 0:
            value, offset = varint(blob, offset)
        elif wire in (1, 2, 5):
            if wire == 2:
                length, offset = varint(blob, offset)
            else:
                length = 8 if wire == 1 else 4
            end = offset + length
            if end > len(blob):
                raise ReaderError('platform_truncated_protobuf')
            value, offset = blob[offset:end], end
        else:
            raise ReaderError('platform_unsupported_protobuf_wire_type')
        yield number, wire, value


def binary(platform, path, params):
    return platform.request(API + path + '?' + urlencode(params), ttl=600, binary=True)


def decode_danmaku(blob):
    items, state = [], 0
    for number, wire, value in fields(blob):
        if number == 2 and wire == 0:
            state = value
        if number != 1 or wire != 2:
            continue
        values = {n: v for n, w, v in fields(value)}
        if not isinstance(values.get(7), bytes) or not (values.get(12) or values.get(1)):
            raise ReaderError('platform_invalid_danmaku_item')
        text = lambda n: values[n].decode('utf-8') if isinstance(values.get(n), bytes) else ''
        items.append({'id': text(12) or str(values[1]), 'time': values.get(2, 0) / 1000,
                      'progress_ms': values.get(2, 0), 'text': text(7), 'mode': values.get(3, 0),
                      'font_size': values.get(4, 0), 'color': values.get(5, 0),
                      'created_at': values.get(8, 0), 'pool': values.get(11, 0),
                      'weight': values.get(9, 0), 'attributes': values.get(13, 0)})
    return sorted(items, key=lambda row: (row['time'], row['id'])), state


def danmaku_controls(source, segment_index=1, offset=0, limit=100, snapshot_id=None):
    video(source)
    integer(segment_index, 'segment_index')
    integer(offset, 'offset', low=0)
    integer(limit, 'limit', high=200)
    if snapshot_id is not None and (not isinstance(snapshot_id, str) or not re.fullmatch(r'[a-f0-9]{24}', snapshot_id)):
        raise ReaderError('snapshot_id must be the ID returned by danmaku')


def danmaku(platform, source, segment_index=1, offset=0, limit=100, snapshot_id=None):
    danmaku_controls(source, segment_index, offset, limit, snapshot_id)
    base = {'material_level': 'danmaku', 'source': source, 'segment_index': segment_index,
            'offset': offset, 'limit': limit, 'items': [], 'segment_complete': False,
            'collection_complete': False, 'is_full_population': False, 'notice': UNTRUSTED,
            'coverage_note': 'Current platform segmented pool, not all historical danmaku. Special/BAS packs and interactive overlays are excluded.'}
    try:
        selected = video(source)
        if snapshot_id:
            path = platform.root / f'danmaku-{snapshot_id}.json'
            if not path.is_file():
                raise ReaderError('Danmaku snapshot not found; restart this segment with offset=0')
            saved = read_json(path)
            if saved['source'] != selected['canonical'] or saved['segment_index'] != segment_index:
                raise ReaderError('Danmaku snapshot belongs to a different part or segment')
            base.update(saved['metadata'])
            items, state = saved['items'], saved['state']
        else:
            if offset:
                raise ReaderError('Use the returned snapshot_id when continuing a segment with offset')
            selected, info = metadata(platform, source)
            part = next((part for part in info.get('pages', []) if part.get('page') == selected['page']), None)
            if not part or not part.get('cid'):
                raise ReaderError('Selected Bilibili part does not exist')
            params = {'type': 1, 'oid': part['cid'], 'pid': info['aid']}
            base.update(bvid=selected['bvid'], aid=str(info['aid']), cid=str(part['cid']), part=selected['page'])
            meta = dict((n, v) for n, w, v in fields(binary(platform, '/x/v2/dm/web/view', params)))
            if meta.get(1, 0):
                return {**base, 'status': 'closed', 'platform_state': meta[1]}
            config = dict((n, v) for n, w, v in fields(meta.get(4, b'')))
            segment_ms, total = config.get(1), config.get(2)
            if (not isinstance(segment_ms, int) or segment_ms <= 0 or
                    not isinstance(total, int) or total < 0):
                raise ReaderError('platform_invalid_danmaku_segments')
            base.update(total_segments=total, segment_seconds=segment_ms / 1000,
                        reported_pool_count=meta.get(8), collection_scope='current_segmented_pool')
            if total == 0 and segment_index == 1:
                return {**base, 'status': 'ready', 'segment_complete': True, 'collection_complete': True, 'next': None}
            if segment_index > total:
                raise ReaderError('segment_index exceeds total_segments')
            blob = binary(platform, '/x/v2/dm/web/seg.so', {**params, 'segment_index': segment_index})
            items, state = decode_danmaku(blob)
            snapshot_id = digest({'source': selected['canonical'], 'segment_index': segment_index, 'blob': blob.hex()})
            details = {key: base[key] for key in ('bvid', 'aid', 'cid', 'part', 'total_segments', 'segment_seconds', 'reported_pool_count', 'collection_scope')}
            write_json(platform.root / f'danmaku-{snapshot_id}.json', {'source': selected['canonical'], 'segment_index': segment_index,
                       'metadata': details, 'items': items, 'state': state})
        if state:
            return {**base, 'status': 'closed', 'platform_state': state}
        if offset > len(items):
            raise ReaderError('offset exceeds segment item count')
        end = min(len(items), offset + limit)
        total = base['total_segments']
        complete = end == len(items)
        continuation = ({'segment_index': segment_index, 'offset': end, 'limit': limit, 'snapshot_id': snapshot_id} if not complete else
                        {'segment_index': segment_index + 1, 'offset': 0, 'limit': limit} if segment_index < total else None)
        return {**base, 'status': 'ready', 'snapshot_id': snapshot_id, 'items': items[offset:end], 'segment_item_count': len(items),
                'segment_complete': complete, 'collection_complete': total == 1 and offset == 0 and complete,
                'next': continuation}
    except PlatformError as error:
        return failure(base, error)
    except (UnicodeError, TypeError, ValueError) as error:
        raise ReaderError('platform_invalid_danmaku_response') from None
