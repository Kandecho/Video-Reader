"""Explicit manual-cookie support; no browser discovery or automatic renewal."""
from contextlib import contextmanager
import hashlib
from pathlib import Path
import shutil
import tempfile

from .common import ReaderError


@contextmanager
def reader_profile(profile):
    original = profile.get('cookies_file')
    if not original:
        yield profile, profile, {'status': 'anonymous', 'authenticated': False, 'account_marker': None}
        return
    source = Path(original)
    if not source.is_file():
        raise ReaderError('Configured YouTube cookie file is missing; supply a replacement or explicitly select anonymous access')
    from yt_dlp.cookies import YoutubeDLCookieJar
    jar = YoutubeDLCookieJar(str(source))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        raise ReaderError('YouTube cookie file must use Netscape cookie format') from None
    if not any(c.domain.lstrip('.') in ('youtube.com', 'google.com') for c in jar):
        raise ReaderError('Cookie file contains no YouTube/Google cookies')
    scope = hashlib.sha256(source.read_bytes()).hexdigest()[:24]
    # yt-dlp saves a cookie jar on exit. Give it a private disposable copy so
    # acquisition cannot overwrite the user-maintained credential file.
    with tempfile.TemporaryDirectory(prefix='video-reader-youtube-') as temporary:
        copied = Path(temporary) / 'cookies.txt'
        shutil.copyfile(source, copied)
        yield {**profile, 'cookies_file': str(copied)}, {**profile, 'cookies_file': None, 'cookie_scope': scope}, {
            'status': 'manual_cookie_supplied', 'authenticated': None, 'account_marker': 'youtube-' + scope,
            'maintenance': 'manual replacement after expiry; no automatic refresh or browser extraction',
            'validity': 'A cookie file alone does not prove the current server login state'}


def status(profile):
    from yt_dlp import YoutubeDL
    from yt_dlp.cookies import YoutubeDLCookieJar
    from yt_dlp.extractor.youtube import YoutubeTabIE
    if not profile.get('cookies_file'):
        return {'status': 'not_configured', 'authenticated': False, 'automatic_renewal': False}
    with reader_profile(profile) as (io_profile, _, authentication):
        jar = YoutubeDLCookieJar(io_profile['cookies_file'])
        jar.load(ignore_discard=True, ignore_expires=True)
        jar.filename = None
        class Quiet:
            def debug(self, *args): pass
            def warning(self, *args): pass
            def error(self, *args): pass
        try:
            with YoutubeDL({'quiet': True, 'logger': Quiet(), 'socket_timeout': 25,
                            'retries': 0, 'extractor_retries': 0}) as ydl:
                ydl.cookiejar = jar
                extractor = YoutubeTabIE(ydl)
                page = extractor._download_webpage('https://www.youtube.com/feed/subscriptions?hl=en', None)
                config = extractor.extract_ytcfg(None, page)
                logged_in = config.get('LOGGED_IN')
        except Exception as error:
            return {**authentication, 'status': 'check_unavailable', 'authenticated': None,
                    'error_type': type(error).__name__, 'automatic_renewal': False}
        return {**authentication, 'status': 'logged_in' if logged_in is True else 'replacement_required' if logged_in is False else 'check_inconclusive',
                'authenticated': logged_in if isinstance(logged_in, bool) else None, 'automatic_renewal': False}
