"""Isolated yt-dlp CLI with request accounting; credentials stay in cookie files."""
from pathlib import Path
import hashlib
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video_reader.acquisition_budget import Budget, request_identity
from video_reader.common import ReaderError, read_json


def observe_response(response, budget, ticket):
    """Retain yt-dlp's exact response type and report actual reads, not opens."""
    original = response.read
    progressed = failed = completed = False
    hasher, received = hashlib.sha256(), 0
    headers = {key.lower(): value for key, value in getattr(response, 'headers', {}).items()}
    try:
        length = int(headers['content-length']) if not headers.get('content-encoding') else None
    except (KeyError, ValueError, TypeError):
        length = None

    def read(*args, **kwargs):
        nonlocal progressed, failed, completed, received
        try:
            value = original(*args, **kwargs)
        except Exception:
            if not failed:
                budget.failed(ticket)
                failed = True
            raise
        zero_read = (args and args[0] == 0) or kwargs.get('amt') == 0
        if value:
            hasher.update(value)
            received += len(value)
            if not progressed:
                budget.succeeded(ticket)
                progressed = True
        amount = args[0] if args else kwargs.get('amt')
        finished = not zero_read and (not value or amount is None or amount < 0 or (length is not None and received >= length))
        if finished and progressed and not failed and not completed:
            budget.succeeded(ticket, hasher.hexdigest())
            completed = True
        elif finished and not progressed and not failed:
            budget.failed(ticket, transient=False)
            failed = True
        return value

    response.read = read
    return response


def main():
    import yt_dlp
    from yt_dlp.networking.exceptions import HTTPError
    spec = read_json(sys.argv[1])
    budget = Budget(spec)
    class BoundedYoutubeDL(yt_dlp.YoutubeDL):
        def urlopen(self, req):
            url = req if isinstance(req, str) else getattr(req, 'url', getattr(req, 'full_url', ''))
            method = 'GET' if isinstance(req, str) else (req.get_method() if hasattr(req, 'get_method') else req.method)
            ticket = budget.reserve(request_key=request_identity(
                url, method, getattr(req, 'data', None), getattr(req, 'headers', None)))
            try:
                response = super().urlopen(req)
            except HTTPError as error:
                budget.reject(error.status)
                budget.failed(ticket, transient=error.status >= 500)
                raise
            except Exception:
                budget.failed(ticket)
                raise
            if method == 'HEAD' or response.status in (204, 304):
                budget.succeeded(ticket)
                return response
            return observe_response(response, budget, ticket)
    # yt-dlp's CLI constructs its module-level YoutubeDL class. This substitution
    # is confined to this worker; argument parsing and all extraction stay upstream.
    yt_dlp.YoutubeDL = BoundedYoutubeDL
    try:
        yt_dlp.main(sys.argv[2:])
    except ReaderError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
