"""Isolated yt-dlp CLI with request accounting; credentials stay in cookie files."""
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from video_reader.acquisition_budget import Budget
from video_reader.common import ReaderError, read_json


def main():
    import yt_dlp
    from yt_dlp.networking.exceptions import HTTPError
    spec = read_json(sys.argv[1])
    budget = Budget(spec)
    class BoundedYoutubeDL(yt_dlp.YoutubeDL):
        def urlopen(self, req):
            budget.reserve()
            try:
                return super().urlopen(req)
            except HTTPError as error:
                budget.reject(error.status)
                raise
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
