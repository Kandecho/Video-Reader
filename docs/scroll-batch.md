# Explicit batch reading

`scroll_batch` is a local reading queue for 1–20 explicitly selected URLs, local files or existing `v_` session IDs. It reuses Reader materials. It does not select recommendations, change interests, schedule runs or send messages.

Call `action=start, sources=[...], task=...`, then `action=next, batch_id=...`. Each response contains one Reader page and `next_ack_cursor`. Inspect the actual images/text before passing that cursor as `after_cursor` to request the next page. If a response was lost or the host restarted, omit `after_cursor`: the unacknowledged page is replayed. Repeating the previous acknowledgment also replays the next pending page instead of skipping it. Keep the batch ID, source and selected speech source.

The queue first delivers adaptive visual samples, then the complete selected speech in stable pages. Incremental ASR handles at most one missing chunk per next step. Completed speech is not decoded again. Earlier text/review changes restart that snapshot explicitly rather than skipping with an old offset. Reader cursors retain source/review/image checks.

`status` distinguishes active, complete delivery, failed items and gaps. An item failure leaves other videos available. After acknowledging the last pending page, `retry` with `item_index` restarts only a failed/incomplete item using Reader caches. Platform pauses and account boundaries remain in force. `offline=true` requires owned source materials and never acquires a missing remote video. Explicit session IDs select existing provenance; URL cache lookup also checks account scope.

CLI uses `scroll.ps1 batch-start --payload batch.json`, where the JSON is `{ "sources": ["v_RETURNED_ID"], "task": "Compare these explanations", "source": "auto" }`. Then use `batch-next BATCH_ID --cursor RETURNED_ACK_CURSOR`, `batch-status BATCH_ID`, or `batch-retry BATCH_ID --index 0`. Omit `--cursor` to replay. The legacy `run.ps1 agent` bridge supports the same commands.

`all_material_delivered` is a transport/processing status. It does not mean that the host understood, proofread or fully observed a video. The host still chooses additional frames, crops, dense windows, evidence and relistening according to the user's question. Sample counts and successful tools cannot certify task completeness. Current daily homepage-first delivery rules remain separately configured and unchanged.

## Verified scope

The rc1 real batch delivered 2,445 existing segments over 51 pages with restart/replay checks and per-item failure isolation. This proves material continuity, not that a host completed substantive comparison or proofreading of those videos. A subsequent 2026-10-28 task completed an actual two-video comparison; see [reading results](../validation/task-reading-20261028/report-source.md). Human quality review and independent-chat understanding remain open; do not restart this completed comparison as the next acceptance task.

Reader rc2 can prepare/commit a processed local review interval with start/end and the returned review_scope. Batch acknowledgments remain transport acknowledgments; they do not automatically submit a review. Review or raw-material changes can require restarting the affected Reader snapshot rather than reusing a stale next cursor. Lightweight tags and exploration are separate later work, not part of this queue.
