"""MCP stdio entry point; no external PYTHONPATH or user site packages needed."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from video_reader.mcp_server import main
main()
