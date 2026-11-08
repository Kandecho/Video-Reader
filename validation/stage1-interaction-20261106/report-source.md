# 阶段 1：日常交互优化实施与工程验收

日期：2026-11-06。范围：用户授权沿六阶段路线开始开发，本批完成阶段 1 已确认摩擦的局部修复及工程验收。没有启动阶段 2 的识别策略修复或后续功能。代码在当前本地源码中，已发布下载包未更新。

## 结果

VR-FLOW-20261105-01 已在同类隔离流程中修复：先取得画面，再启动增量转写，仍能继续取得原画面尾页；转写持锁时也无需等待。后续画面页不重复首批语音。来源、原图、原语音及校对版本仍保留，文字续读不混入新修订。

任务状态、结果回看及追问路径沿用既有接口。任务保留原要求、附言、产物路径及摘要、覆盖范围与完成依据；查询不将交付推成宿主读完。源码检查及跨 Reader 实例的结果查询回归未确认需要重做这些流程的新问题。

## 实现

- Reader 在原读取持锁区取得的缓存帧记录，交给交付装饰器冻结剩余画面；内部携带字段在返回前移除，也不改变 `_delivery=False` 的传统 Python 分页。
- 每个后续画面页是普通独立快照，以 next_delivery_cursor 串联。每份快照仍有唯一的 canonical JSON，material_parts 可独立无损还原。帧 ID、顺序、原像素和分页边界冻结，进程重启或 page_frames 配置变化不会重排。
- 后续画面页省去首批 speech。首批原文、证据及 speech.next_cursor 保留；后续绑定继续记录原 speech_snapshot、review_revision 和来源、媒体、账号、参数，不能把这份旧画面交付当作最新语音。
- 可选弹幕仍保留同一快照、原文及 blocked/closed/partial 状态；speech 段关联不变，nearest_sampled_frame 按该页重新计算，不重新联网。
- 数字冻结页直接返回，不启动 worker。文字及历史画面的动态 `:next` 续页通过 MCP/CLI 复用 Jobs 的短等待、任务复用、进度与错误接口。video_continue 的 wait_seconds / CLI --wait 默认 1 秒，通用 job start 支持 continue_read。同步 Python API 继续兼容。
- 动态文字/旧游标的来源、语音、校对与诊断检查未放松。旧游标遇语音变化仍明确拒绝；应重发相应原请求以选择新材料。原媒体或冻结图片变化仍报错。

主要代码：[交付](../../video_reader/delivery.py)、[Reader](../../video_reader/reader.py)、[弹幕关联](../../video_reader/aligned_danmaku.py)、[共享任务](../../video_reader/jobs.py)、[MCP](../../video_reader/mcp_server.py)、[CLI](../../video_reader/cli.py)。

## 证据和验证

原问题与两种复现时序见[11 月 5 日确认记录](../paging-flow-20261105/report-source.md)，该历史记录的 confirmed_not_fixed 指当时状态。

本批回归使用固定 12/20 张图片和模拟 ASR 输出，走真实 transcript、交付及会话锁；另用本地 FFmpeg 合成视频、真实 worker 和 CLI/MCP 适配器验证跨进程接续。没有重跑原用户视频或真实识别模型，人工解码阻塞用于控制时序，不是 ASR 性能基准。

| 验证 | 结果 |
|---|---|
| 首批后新增一段 ASR，再跨进程续图 | 20 张图按原 ID 和顺序完整接续；后续画面没有重复 speech |
| ASR 已持会话锁时续图 | 立即读取原后 4 张图，不调用 read 或取得会话锁 |
| 校对修订变化 | 冻结画面仍保留原绑定；文字游标拒绝新版本 |
| 历史动态画面游标 | 未变更时可用，新增 ASR 后仍严格拒绝混用 |
| 动态文字续页等待锁 | MCP 返回 job ID，CLI continue / job start 复用同一活跃任务；解锁后取到正确尾段 |
| 冻结视觉页经过 CLI/MCP | 无需 job、不等锁，返回一致的帧身份 |
| 大弹幕与无损碎片 | 每个视觉快照分别还原；原文、快照及逐页图关联保留 |
| 媒体/图片变更 | 显式拒绝，未替换成其他证据 |
| 保存结果后重建 Reader 查询 | 原要求、产物、摘要、覆盖说明及独立完成依据保留 |

完整项目检查：`python -m unittest discover -s tests -v`，**347 项通过，72.383 秒，无失败或跳过**。包含交付、校对、job、MCP/CLI、批读、任务、弹幕及导出等既有回归。源测试见 [delivery](../../tests/test_delivery.py)、[jobs](../../tests/test_jobs.py)、[aligned_danmaku](../../tests/test_aligned_danmaku.py)、[reading_tasks](../../tests/test_reading_tasks.py)。完整运行日志留在本地 `.test-work/stage1-unittest.log`，不作为公开材料打包。

初次在受限执行环境运行既有跨进程 MCP 测试，卡在 Windows asyncio 的 socketpair 本地回环连接，尚未进入 Reader 业务；获取调用栈后终止该轮，在允许本地回环的执行环境重跑完整测试并通过。该环境限制未作为产品失败，也未通过改业务代码规避。

独立审阅在实现前识别了碎片边界、弹幕重关联及并发缓存替换风险，采用独立冻结页和原读取帧记录后复查；补齐 CLI job operation 枚举，未留下阻断性问题。

## 验收范围和接续

阶段 1 本批工程验收通过：已确认流程得到改善，等待有状态与下一步，正文、原图和修订保全，任务结果可回查，完整项目回归通过。日常真实视频使用反馈继续保留；没有把合成测试写成全部宿主、平台或模型的全面验收。

长访谈转写本身的过渡重复条目未删除，原段、时间、词证据和修订继续保留；本批减少的是画面分页时重复交付相同首批语音。Scroll 批读既有段 ID/签名去重保留。识别策略、评论尾页及弹幕错误诊断按阶段 2 处理。

已连接 Reader MCP 需重启加载本地新代码。新 read 获得预先冻结的画面续页；历史动态游标不会自动迁移。生成的 Codex/Claude 薄适配器已同步源码 Skill。本批未发布新资产、变更默认模型、发送消息或增加同步/调度。
