"""Metadata, subtitles and native image previews without full-media downloads."""
from bisect import bisect_right
from io import BytesIO
import json
import math
from pathlib import Path
from types import SimpleNamespace

from PIL import Image, ImageDraw, ImageFont

from .platform import PlatformError
from .common import ReaderError, UNTRUSTED, read_json, write_json, stamp
from .discovery import _candidate, _search_params
from .sources import resolve
from .bilibili_material import captions as bilibili_captions


def candidates(platform, query='', limit=10, *, fresh=False):
    ttl = 0 if fresh else platform.config['preview']['recommendation_ttl_seconds']
    if query:
        signing = SimpleNamespace(jar=platform.jar, request=lambda url: platform.request(
            url, ttl=platform.config['preview']['material_ttl_seconds']))
        params = _search_params(signing, {'keyword': query, 'search_type': 'video', 'page': 1,
                                           'page_size': limit, 'order': 'pubdate'})
        data = platform.json('/x/web-interface/wbi/search/type', params, ttl=ttl)
        rows = data.get('result') or []
    else:
        data = platform.json('/x/web-interface/index/top/feed/rcmd',
                             {'fresh_type': 3, 'ps': limit, 'version': 1}, ttl=ttl)
        rows = data.get('item') or []
    result, seen = [], set()
    for raw in rows:
        if not isinstance(raw, dict) or raw.get('is_ad') or raw.get('goto', 'av') != 'av':
            continue
        item = _candidate(raw)
        if item and item['bvid'] not in seen:
            seen.add(item['bvid'])
            result.append(item)
    return result[:limit]


def snapshot_positions(snapshot, desired):
    indices = snapshot.get('index') or []
    if (not isinstance(indices, list) or not indices
            or any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 for t in indices)
            or indices != sorted(indices)):
        raise PlatformError('snapshot_index_unavailable')
    indices = indices[1:] if indices[:2] == [0, 0] else indices
    columns, rows = int(snapshot['img_x_len']), int(snapshot['img_y_len'])
    if not indices or min(columns, rows) <= 0:
        raise PlatformError('snapshot_grid_invalid')
    positions = []
    for target in desired:
        index = max(0, bisect_right(indices, target) - 1)
        sprite, tile = divmod(index, columns * rows)
        positions.append({'requested_time': target, 'time': indices[index], 'sprite': sprite,
                          'column': tile % columns, 'row': tile // columns})
    return positions


def validate_snapshot(snapshot):
    """A code=0 response is not usable without its timeline and image grid."""
    if not isinstance(snapshot, dict):
        raise PlatformError('snapshot_invalid_data')
    try:
        positions = snapshot_positions(snapshot, [0])
        images = snapshot.get('image')
        if not isinstance(images, list) or not images or any(not isinstance(url, str) or not url for url in images):
            raise PlatformError('snapshot_images_unavailable')
        width, height = int(snapshot['img_x_size']), int(snapshot['img_y_size'])
        if not 0 < width <= 4096 or not 0 < height <= 4096:
            raise PlatformError('snapshot_tile_size_invalid')
        if positions[0]['sprite'] >= len(images):
            raise PlatformError('snapshot_grid_invalid')
        count = len(snapshot['index']) - (1 if snapshot['index'][:2] == [0, 0] else 0)
        if count > int(snapshot['img_x_len'])*int(snapshot['img_y_len'])*len(images):
            raise PlatformError('snapshot_grid_invalid')
    except (KeyError, TypeError, ValueError, OverflowError):
        raise PlatformError('snapshot_grid_invalid') from None


def snapshot_material(platform, params, ttl):
    """One bounded refresh, same account/budget. Invalid payloads are never cached."""
    errors = []
    trace_start = len(getattr(platform, 'trace', []))
    for attempt in range(2):
        try:
            snapshot = platform.json('/x/player/videoshot', params,
                                     ttl=ttl, validate=validate_snapshot)
            return snapshot, {'attempts': attempt+1, 'prior_errors': errors,
                'invalid_cache_bypassed': any(item.get('cache') == 'invalid'
                    for item in getattr(platform, 'trace', [])[trace_start:])}
        except PlatformError as error:
            # Restrictions, budgets, offline misses and transport errors are not
            # an invitation to change identity or resume a paused transport.
            if platform.offline or not error.code.startswith('snapshot_') or attempt:
                raise
            errors.append(error.code)


def controls(density='light', max_frames=None):
    if density not in ('light', 'dense'):
        raise ReaderError('density must be light or dense')
    count = (5 if density == 'light' else 48) if max_frames is None else max_frames
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 120:
        raise ReaderError('max_frames must be an integer between 1 and 120')
    return count


def native_frames(platform, snapshot, duration, directory, *, count=5, max_sprites=2):
    wanted = [round(max(0, duration - 1) * index / max(1, count - 1), 2) for index in range(count)]
    positions = snapshot_positions(snapshot, wanted)
    width, height = int(snapshot['img_x_size']), int(snapshot['img_y_size'])
    if not 0 < width <= 4096 or not 0 < height <= 4096:
        raise PlatformError('snapshot_tile_size_invalid')
    sprites, frames, selected = {}, [], set()
    for index, position in enumerate(positions):
        sprite = position['sprite']
        if sprite not in sprites:
            if len(sprites) >= max_sprites or sprite >= len(snapshot['image']):
                continue
            url = snapshot['image'][sprite]
            body = platform.request('https:' + url if url.startswith('//') else url, ttl=86400, binary=True)
            image = Image.open(BytesIO(body))
            if image.width * image.height > 40_000_000:
                raise PlatformError('snapshot_image_too_large')
            sprites[sprite] = image.convert('RGB')
        left, top = position['column'] * width, position['row'] * height
        identity = (sprite, left, top)
        if identity in selected:
            continue
        selected.add(identity)
        image = sprites[sprite]
        if left + width > image.width or top + height > image.height:
            raise PlatformError('snapshot_tile_outside_sprite')
        target = directory / f'preview-{index}.jpg'
        image.crop((left, top, left + width, top + height)).save(target)
        frames.append({'id': f'preview_{index}', 'time': position['time'], 'path': str(target.resolve()),
                       'requested_time': position['requested_time'], 'precision': 'approximate_native_snapshot'})
    if not frames:
        raise PlatformError('snapshot_images_unavailable')
    return frames


def contact_sheet(result, directory):
    frames = result.get('frames') or []
    if not frames:
        return None
    columns = min(8, len(frames))
    cell_width, cell_height, label_height = 240, 135, 24
    rows = (len(frames) + columns - 1) // columns
    image = Image.new('RGB', (columns * cell_width, 36 + rows * (cell_height + label_height)), (20, 20, 20))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=14)
    precision = result.get('frame_precision', 'approximate_native_snapshot')
    label = 'cached source frames' if precision == 'source_frame' else 'approximate native snapshots'
    draw.text((8, 8), f"{result['bvid']} P{result['part']} | {label}", font=font, fill='white')
    cells = []
    for index, frame in enumerate(frames):
        x, y = (index % columns) * cell_width, 36 + (index // columns) * (cell_height + label_height)
        with Image.open(frame['path']) as source:
            tile = source.convert('RGB')
        tile.thumbnail((cell_width, cell_height))
        image.paste(tile, (x + (cell_width - tile.width) // 2, y + (cell_height - tile.height) // 2))
        draw.text((x + 4, y + cell_height + 3), f"{index + 1:02d} {stamp(frame['time'])}", font=font, fill=(255, 230, 100))
        cells.append({'frame_id': frame['id'], 'time': frame['time'], 'path': frame['path']})
    path = directory / 'contact-sheet.jpg'
    image.save(path, quality=90)
    return {'path': str(path.resolve()), 'frame_count': len(frames), 'columns': columns,
            'cells': cells, 'precision': precision, 'source': result['url']}


def preview(platform, source, *, density='light', max_frames=None, make_sheet=False):
    count = controls(density, max_frames)
    if not isinstance(make_sheet, bool):
        raise ReaderError('contact_sheet must be true or false')
    resolved = resolve(source, shortlink_resolver=platform.resolve_shortlink)
    if resolved['platform'] != 'bilibili':
        raise ReaderError('Light preview currently supports Bilibili BV/URL sources')
    bvid, part_number = resolved['bvid'], resolved['page']
    directory = platform.root / f'{bvid}-p{part_number}'
    if density != 'light' or count != 5:
        directory /= f'{density}-{count}'
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / 'preview.json'
    ttl = platform.config['preview']['material_ttl_seconds']
    if platform.offline and manifest.is_file():
        result = read_json(manifest)
        if all(Path(frame['path']).is_file() for frame in result.get('frames', [])):
            if make_sheet:
                result['contact_sheet'] = contact_sheet(result, directory)
            return result
    info = platform.json('/x/web-interface/view', {'bvid': bvid}, ttl=ttl)
    pages = info.get('pages') or []
    if not 1 <= part_number <= len(pages):
        raise ReaderError('Preview part is outside this video')
    part = pages[part_number - 1]
    cid, duration = part['cid'], float(part.get('duration') or 0)
    owner = info.get('owner') or {}
    result = {'bvid': bvid, 'part': part_number, 'cid': cid, 'url': resolved['canonical'],
              'title': info.get('title'), 'description': info.get('desc'), 'duration_seconds': duration,
              'uploader': owner.get('name'), 'uploader_id': str(owner['mid']) if owner.get('mid') else None,
              'uploader_url': f"https://space.bilibili.com/{owner['mid']}" if owner.get('mid') else None,
              'density': density, 'requested_frames': count,
              'caption': None, 'frames': [], 'gaps': [], 'material_level': 'preview',
              'reading_status': 'previewed_not_read', 'notice': UNTRUSTED}
    try:
        caption = bilibili_captions(lambda url: platform.request(url, ttl=ttl), bvid, cid)
        if caption['status'] != 'ready':
            result['gaps'].append('no_platform_caption')
        else:
            result['caption'] = {'segments': caption['segments'], 'language': caption['track']['language'],
                                 'kind': caption['track']['kind'], 'proofread': False}
            if not caption['segments']:
                result['gaps'].append('empty_caption_not_proof_of_silence')
    except PlatformError as error:
        result['gaps'].append('caption:' + error.code)
    try:
        snapshot, result['visual_recovery'] = snapshot_material(platform, {'bvid': bvid, 'cid': cid, 'index': 1}, ttl)
        result['frames'] = native_frames(platform, snapshot, duration, directory, count=count,
                                         max_sprites=2 if density == 'light' else 8)
    except (PlatformError, OSError, ValueError, KeyError) as error:
        result['gaps'].append('visual:' + (error.code if isinstance(error, PlatformError) else type(error).__name__))
    result['visual_sampling'] = {'requested_frames': count, 'returned_frames': len(result['frames']),
                                 'precision': 'approximate_native_snapshot', 'complete_continuous_coverage': False}
    write_json(manifest, result)
    if make_sheet:
        result['contact_sheet'] = contact_sheet(result, directory)
    return result


def comments(platform, bvid):
    from .community import comments_sample
    return comments_sample(platform, bvid)
