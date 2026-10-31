"""Shared MCP evidence rendering without importing either server."""
import base64
import json
from pathlib import Path

from mcp.types import ImageContent, TextContent


def pack(result):
    blocks = [TextContent(type='text', text=json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')))]
    if result.get('material_level') == 'preview_batch' and 'items' in result:
        for item in result.get('items', []):
            _images(item, blocks)
        return blocks
    _images(result, blocks)
    return blocks


def _images(result, blocks):
    sheet = result.get('contact_sheet')
    if sheet:
        blocks.append(TextContent(type='text', text=f"Storyboard of {sheet['source']}: {sheet['frame_count']} labeled frames ({sheet['precision']}); not complete reading"))
        blocks.append(ImageContent(type='image', mimeType='image/jpeg', data=base64.b64encode(Path(sheet['path']).read_bytes()).decode('ascii')))
        return
    for frame in result.get('visual', {}).get('frames', result.get('frames', [])):
        blocks.append(TextContent(type='text', text=f"Video frame {frame['id']} at source time {frame['time']} {frame.get('video_url', '')}"))
        blocks.append(ImageContent(type='image', mimeType='image/jpeg', data=base64.b64encode(Path(frame['path']).read_bytes()).decode('ascii')))
        reference = frame.get('temporal', {}).get('stable_reference')
        if reference and reference['path'] != frame['path']:
            blocks.append(TextContent(type='text', text=f"Local text stability reference at source time {reference['time']}; not proof of semantic finality"))
            blocks.append(ImageContent(type='image', mimeType='image/jpeg', data=base64.b64encode(Path(reference['path']).read_bytes()).decode('ascii')))
