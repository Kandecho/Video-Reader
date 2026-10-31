"""CLI entry point usable with the bundled Python's isolated (-I) mode."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from video_reader.cli import main
raise SystemExit(main())
