"""Optional interval/window scheduling; no OS task registration or catch-up queue."""
from datetime import datetime, timedelta, timezone
import math
import random
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from video_reader.common import ReaderError


def local_zone(name):
    if name == 'local':
        return datetime.now().astimezone().tzinfo
    if name == 'UTC':
        return timezone.utc
    if isinstance(name, str) and re.fullmatch(r'[+-]\d{2}:\d{2}', name):
        hours, minutes = map(int, name[1:].split(':'))
        if hours > 23 or minutes > 59:
            raise ReaderError('Invalid timezone offset')
        return timezone(timedelta(minutes=(hours * 60 + minutes) * (-1 if name[0] == '-' else 1)))
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ReaderError('Timezone unavailable; use local, UTC, a UTC offset, or install IANA timezone data') from None


def clock_minutes(value):
    if not isinstance(value, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
        raise ReaderError('Wake window times must be HH:MM')
    hours, minutes = map(int, value.split(':'))
    return hours * 60 + minutes


def validate(wake):
    if not isinstance(wake.get('enabled'), bool):
        raise ReaderError('wake.enabled must be true or false')
    local_zone(wake['timezone'])
    if wake['mode'] not in ('fixed', 'range'):
        raise ReaderError('Wake mode must be fixed or range')
    if not isinstance(wake['windows'], list):
        raise ReaderError('Wake windows must be a list')
    for window in wake['windows']:
        if not isinstance(window, dict) or set(window) != {'start', 'end'}:
            raise ReaderError('A wake window needs start and end')
        if clock_minutes(window['start']) == clock_minutes(window['end']):
            raise ReaderError('Wake window start and end must differ; use [] for all day')
    keys = ('interval_seconds',) if wake['mode'] == 'fixed' else ('min_seconds', 'max_seconds')
    if wake['enabled']:
        for key in keys:
            value = wake.get(key)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 1:
                raise ReaderError('Enabled wake requires positive interval parameters')
        if wake['mode'] == 'range' and wake['min_seconds'] > wake['max_seconds']:
            raise ReaderError('Wake min_seconds must not exceed max_seconds')


def in_window(instant, wake):
    if not wake['windows']:
        return True
    local = instant.astimezone(local_zone(wake['timezone']))
    minute = local.hour * 60 + local.minute
    for window in wake['windows']:
        start, end = clock_minutes(window['start']), clock_minutes(window['end'])
        if start <= minute < end if start < end else minute >= start or minute < end:
            return True
    return False


def next_run(instant, wake, uniform=random.uniform):
    validate(wake)
    if not wake['enabled']:
        return None
    delay = wake['interval_seconds'] if wake['mode'] == 'fixed' else uniform(wake['min_seconds'], wake['max_seconds'])
    candidate = instant.astimezone(local_zone(wake['timezone'])) + timedelta(seconds=delay)
    if in_window(candidate, wake):
        return candidate.astimezone(timezone.utc)
    openings = []
    for days in (0, 1, 2):
        day = candidate.date() + timedelta(days=days)
        for window in wake['windows']:
            minutes = clock_minutes(window['start'])
            opening = datetime(day.year, day.month, day.day, minutes // 60, minutes % 60, tzinfo=candidate.tzinfo)
            if opening >= candidate:
                openings.append(opening)
    if not openings:
        raise ReaderError('No next wake opening could be computed')
    return min(openings).astimezone(timezone.utc)
