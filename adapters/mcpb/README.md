# Video Reader + Scroll MCP bundles

Two Windows MCPB adapters connect to the same prepared Video Reader installation:

- `video-reader`: video materials, transcripts, frames, comments, and the independent task queue/history.
- `scroll-agent`: a separate Bilibili account, personal feed, inbox, feedback and explicitly authorized delivery. Account workflows have real usage; scheduling and continued background consumption remain limited or under trial.

Prepare the Windows core first using [installation](https://github.com/Kandecho/Video-Reader/blob/main/docs/installation.md), including its `.venv/Scripts/python.exe` and `config.json`. These small bundles do not install Python, FFmpeg, models or accounts. The full project, including both adapters, is released together. See [capability status](https://github.com/Kandecho/Video-Reader/blob/main/docs/capabilities.md).

In a host that supports MCPB, install the desired `.mcpb` file from the [project releases](https://github.com/Kandecho/Video-Reader/releases). Select the core installation folder. Optionally select a different existing configuration file; otherwise the adapter uses `config.json` in the core folder. Install both bundles for the full workflow. Use the same core and configuration to share materials and state. Avoid registering an identical service twice through another adapter in the same host.

The bundles expose existing MCP stdio services, not an HTTP endpoint. Installing Scroll does not start a daily run, inbox polling or sending. Reader does not require a Bilibili login for local task queries. Platform reading and account actions retain the core's login and authorization requirements. Local processing is the default; no cloud fallback is added.

Build both artifacts with `python tools/build_mcpb.py OUTPUT_DIRECTORY`. The output must be new. Each archive contains only `manifest.json`, `server/launch.py`, this README and MIT LICENSE. Validate manifests with the official `@anthropic-ai/mcpb` CLI. Build output and publisher credentials do not belong in Git.

The manifest/configuration and actual stdio calls are tested on Windows. Installing through a particular desktop host's MCPB UI is a separate compatibility check; the protocol test does not claim it.
