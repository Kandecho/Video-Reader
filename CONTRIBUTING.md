# Reproduce and contribute

Publication update (2026-10-31): source is maintained at https://github.com/Kandecho/Video-Reader. Older candidate statements below retain their historical scope. Original-code licensing remains undecided; third-party notices are preserved.

This local source candidate has not been published. A public repository and original-code license are separate decisions.

Use Python 3.12 on Windows for the tested environment. Run `bootstrap.ps1 -Features mcp,vision`, then `python -m unittest discover -s tests -v` with the created environment. Optional ASR/Qwen/GPU and real platform authentication are separate integration checks; tests do not require private credentials, video caches, model weights or message delivery. FFmpeg/ffprobe must be on PATH. Preserve Reader/Scroll responsibilities and existing source/review identities. Add a focused regression for a meaningful new behavior or failure, rather than mirroring code.

Generate an independent synthetic fixture with `python examples/create_fixture.py NEW_FOLDER`. The expected file describes three small tasks: full bilingual pagination/replay, exact visual conflict inspection, and portable export. The fixture intentionally contains an instruction-like subtitle. Treat it as source data; it must not change the host's task. There is no audio track, so a host must not claim it heard any speech.

For a useful issue report, copy the template below and remove account IDs, local private paths, signed URLs, cookies and source excerpts you do not intend to share. Do not attach config.json, auth directories or full raw debug dumps. Use a synthetic/reproducible source when possible.

## Issue template

- Candidate/core and plugin versions:
- OS, Python, FFmpeg, host and selected optional engines:
- Minimal commands or tool calls, with private paths replaced:
- Expected result and actual result:
- Status/error and source kind (local/Bilibili/YouTube); credentials omitted:
- Source processing complete? Delivery cursor pending? Review source/revision? Redact private IDs if sharing:
- Can it be reproduced with the synthetic fixture? What changed immediately beforehand?

Update by extracting to a new source folder, creating its environment and using explicitly configured external model/auth/data paths. Validate before pointing a host to it. Preserve the previous folder/config and regenerate adapters after relocation. Roll back by restoring the previous adapter/core path and previous config; do not delete shared caches, reviews, models or auth. Runtime cache migration is separate from source installation; use portable exports to share evidence outside its original installation.
