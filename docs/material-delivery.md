# Material identity and consumption


## 0.10.0rc6 诊断状态与首屏材料

大阅读的 `view=reading` 先提供 `reading_projection`，包含原像素取样图和容得下的完整字幕段。它是阅读入口，`delivery.next_cursor` 后仍保留 canonical 无损材料；并未减少处理深度或全片覆盖要求。投影只交付一部分时，用 `remaining_in_snapshot` 明示，暂不暴露可能跳过材料的 speech/visual 下一页入口。单图本身超图片预算时仍明确延后。既有冻结页不重排。

`text_status=unverified_candidate` 表示可疑机器识别原文；`recognition_assessment` 与 source_processed 处理覆盖分开。Qwen 的 `alignment_unresolved` / `unplaced_candidates` 保留 raw_text、input_range、owner_range、raw_alignment，不制造归属时间；该状态不等于声学无人声，尚存候选时 review.complete 为 false。处理过的旧缓存直接派生这些字段，原 profile、段 ID 与校对历史不变。新动态游标绑定诊断变化，旧冻结页仍可读。

元数据获取新增 extracting_source_metadata / retrying_source_metadata 阶段，仅明确网页瞬时超时或断连恢复一次；限制、预算耗尽和暂停不自动恢复。最终 AcquisitionError / job.error.details 保留 stage 与 attempts，成功也保留 acquisition.metadata_extraction 的恢复记录。下载前重新核对 B 站 part/CID。预览会在缓存写入前检查索引与图格，在线旁路旧坏缓存并至多一次有界重取；离线保留缺口。

Windows 状态读写共享 job 的短时 .status.lock，包括启动失败兜底，避免读 JSON 与原子替换交错。它不持有视频材料锁。详见 [修复验收](../validation/diagnosis-repairs-20261031/report-source.md)。续期不在本轮验证范围。


`video_open` and `video_read` accept a task description, bounds, exact cue timestamps and a strategy. The host interprets the user's question. Adaptive extraction supplies speech-cue frames, scene changes and sparse timeline checks; it is not an independent question-answering model and never certifies task completeness. Full learning requires all chosen speech and necessary visuals; focused questions expand only as evidence requires. Density and resolution are independent of token budgets.

CLI/MCP use adaptive initial extraction (up to 12 frames). Legacy Python Reader calls keep uniform defaults. Uniform and scene strategies retain explicit caps; dense defaults to 48 and uses exact source timestamps, avoiding the old uniform helper's 2 fps limit on short videos. No perceptual deduplication drops code/text differences or black frames. All strategies are samples, not continuous event coverage.

Read responses expose processing/cache use and delivery JSON/image bytes. Transcription defaults to one missing chunk per CLI/MCP call, while `max_chunks=null` / `--complete-range` retains blocking complete-range processing. Decoding checkpoints survive failure. Paging ready material never starts more ASR. Repeat the original transcript request to process remaining ranges, then consume the new snapshot; segment IDs identify reused material. Qwen seam assembly can change its snapshot when new neighbors arrive, so old cursors never silently mix the two.

## Durable continuation

Core 0.10.0rc4 supports optional timestamped audience material through `include_danmaku=False` on open/read and export (CLI `--include-danmaku`). Enabled reads provide a separate `danmaku` section for the same Bilibili session part/CID and `[start,end)` range. Default requests do not acquire it.

Items retain original ID/text, progress_ms, posting created_at and playback timestamp_seconds. Overlapping speech IDs and nearest sampled frame ID/time/delta provide temporal joins, not semantic agreement. Speech references may point to later speech pages. Missing captions/frames leave empty/null joins. Real frame timestamps can differ from a requested danmaku timestamp.

Audience content and failure/closed states freeze under session snapshots. Standard lossless delivery cursors preserve them across frame pages and restarts without new acquisition. Gaps retain main material and successful audience items. Account mismatch and changed original CID never attach another pool. Fresh reads can reacquire. Export opt-in includes only acquired snapshots for selected reads; it never fetches online. not_acquired differs from an empty ready pool.

Use `video_continue(session_id,cursor)` or `continue SESSION CURSOR`. `delivery.next_cursor` continues the current visual/text delivery; `speech.next_cursor` continues speech accompanying a read. Cursors persist on disk and bind source identity, account/credential scope, selected part/range, source/context/view, speech snapshot, review revision and position.

Ordinary pages retain their original JSON shape. Oversized pages use `material_parts`, a lossless JSON-pointer representation. Object/array declarations preserve structure, scalar values preserve type, and strings have zero-based Unicode character spans plus total_characters. Segment parts retain segment_id/start/end. Append each string span in order; `video_reader.delivery.restore` is the reference decoder. Word/OCR/correction evidence follows the same rules, with nothing silently dropped. Image pages keep original pixels and IDs. A single image larger than the configured image budget is still delivered whole, never silently compressed or omitted.

Generated pages are frozen. They remain readable after a review changes. Fetching a later, not-yet-generated page checks its binding and fails explicitly if material changed, including a concurrent change during continuation. Restart the original request rather than mixing revisions. Changed local files and missing frozen image assets are explicit errors. Legacy numeric offsets/pages remain supported but do not freeze identity themselves.

Native previews use separate `p_` material identities and the same continuation tool. They do not become full-media sessions or affect cached-video discovery. The preview's source_session_id identifies owned media when available. Native thumbnail times remain approximate. Sheet labels/cells are navigation, not a substitute for inspecting legible source pixels with video_frame or exact timestamp reads.

## Response readiness and current proofreading

The 2026-10-29 user decision treats time to a useful answer as part of the reading experience. Enough evidence for the current answer and all materials reviewed are distinct judgments; response readiness is a host judgment, not a new API field. Unchecked material must remain available with provenance. Full requested summaries still require their scope to be covered.

The current runtime/installed Skill still carries its earlier proofreading workflow; that behavior has not been revised in this documentation pass. Reader stores host-authored semantic corrections. OCR differences and fresh ASR are candidates, not an independent first-pass semantic review. See [current decisions](decisions.md) and [route](../planning/roadmap-20261021-source.md).

## Meaning of completion

- Source processed: decoding/captions cover the requested interval; no_speech still records processed coverage.
- Delivered: material returned to a host, with bytes and next cursor. It may not have been opened.
- Observed: the host actually saw/read it; the component cannot infer this from a tool call.
- Reviewed: the host committed minimal evidence-backed corrections and reviewed IDs for that speech snapshot.
- Accurate: an evidentiary judgment with uncertainty, not a boolean implied by any of the above.

Sound inspection measures one-second RMS/peak levels and quiet/level-change cues, in at most 600-second windows. It does not identify music/emotion/events, and does not remove speech. Acquisition budgets count native API requests and yt-dlp urlopen calls under one account pause/budget ledger; internal redirects in transport are not separately measured. Cache hits remain available while online acquisition is paused.

## Portable export

Choose source/context and an explicit review revision. Export creates a new folder with evidence.json, index.html and relative assets. The JSON retains raw/corrected wording, original word timing, reasons, issues, source-scoped terms, selected revision history and referenced images. Historical revisions reconstruct from the saved history; incomplete histories fail instead of falling back to latest. Full video/model/runtime files are not implicitly bundled. Moving the artifact folder preserves its image references. No public upload occurs.

## 局部校对和增量补读（0.10.0rc2）

review prepare/status 可指定 start/end；该任务区间处理完成后可单独校对。prepare 返回 review_scope，commit 必须原样带回；同时返回 scope_review 和全片 review。补读不丢失旧审阅，原文和时间相同的段落保留 ID；新增或变化段落待审。稳定的校对文档 ID 与原文材料指纹分别绑定：旧 :next 仍拒绝材料变化，数字页仍回放原页。导出 evidence.json 同时记录 material_snapshot_id 和选择的 review revision。

新 Whisper 解码只使用显式 context，不从视频标题自动生成提示。旧标题提示结果及校对不改写；默认可复用旧缓存，新的默认解码另存无提示轨。需要主动重读旧完整区间时显式传 context 空串；旧轨通过原 context 可再次读取。
