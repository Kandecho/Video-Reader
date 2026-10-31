"""Shared-installation entry for Scroll Agent CLI and its independent MCP."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
if sys.argv[1:2] == ['--mcp']:
    from scroll_agent.mcp_server import main
else:
    from scroll_agent.cli import main
raise SystemExit(main())
