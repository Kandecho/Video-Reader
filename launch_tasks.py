"""Shared-installation task CLI entry."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from reading_tasks.cli import main
raise SystemExit(main())
