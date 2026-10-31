# Acquisition spike, 2026-10-22

This is an isolated experiment, not a new production MCP or plugin release.
It imports the shared core at `D:/IA/apps/video-reader`, uses its own managed
account, and reads existing full media by path. It does not copy models,
credentials, environments or existing full-media caches.

Run with the existing `.venv/Scripts/python.exe -I` and these saved scripts:

- `test_prototype.py`: fourteen local tests; no live platform requests.
- `run_spike.py online`: a finite live experiment, at most 24 requests in this
  experiment's persisted gate, 2 MB per response, no automatic retries. Reads
  recommendations, metadata, captions, native snapshot sprites, one comment page
  and an XML danmaku sample. No full-media download or platform write interface.
- `run_spike.py local-deep`: read two existing media files and generate local
  frames. No ASR, media copy or source-manifest modification.
- `run_spike.py summary`: display the saved result as UTF-8, with no network.
- `replay.py`: replay saved materials with the network transport disabled.
  This prototype still resolves its account scope from the component's local
  credential record; it does not validate the login online or refresh it.
- `alignment_check.py`: compare selected native tiles against cached source
  frames. The pixel diagnostic is not a general accuracy benchmark.
- `boundary_check.py`: preserve the original indexing diagnosis. This diagnostic
  deliberately uses unadjusted raw indices; it is not the corrected selector.
- `summarize.py`: persist agent observations, not inferred user preferences.

`private-cache/` holds only newly fetched preview/JSON/sample responses for this
experiment. These files can contain source URLs and viewer text; do not publish
them as a public dataset. `results/` contains measured evidence and images.
No browser cookies or other applications' configuration are read.

The 2-second pacing and 24-request cap are laboratory load limits, not documented
platform-safe thresholds. The gate covers only this prototype, not production
clients or yt-dlp. Restriction recovery is tested with simulated replies, not by
triggering real restrictions. Do not reset the gate merely to bypass a refusal.

The first online run completed and saved its results, then its terminal output
failed on an emoji under Windows GBK. UTF-8 output was fixed and the saved summary
was replayed without repeating the live requests. The results and trace remain
the original online measurements.

The prototype initially treated a duplicated leading zero in three snapshot
indices as a real tile. The corrected selector removes that leading placeholder
only when the duplicate exists. Four local source-time comparisons support the
fix for this sample; native snapshot times remain approximate.

Next integration should reuse the shared core, existing source identities and
reading/review contracts. Do not promote this directory into a second independent
account service, recommendation daemon or model runtime.
