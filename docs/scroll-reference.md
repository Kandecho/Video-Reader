# Scroll Agent 普通工作流参考

身份：共享安装 0.10.0rc6 的普通单轮、记忆和可选唤醒操作参考，状态与恢复更新于 2026-11-04；本机每日首条策略、任务状态及依赖以[日试用运行说明](daily-trial.md)为准。

Scroll 消费 Reader 材料，负责个人账号流及记录；通用任务/结果由 reading_tasks 提供，旧命令保留适配。默认每轮 10 个候选、最多 3 条预览、最多推荐 2 条可配置。通用主题检索无需个人工作流。

当前 MCP 为 `scroll_round` / `scroll_memory` / `scroll_batch` / `scroll_inbox` / `scroll_queue` / `scroll_triage` / `scroll_report`，操作契约见 [Scroll Skill](../scroll-skill/SKILL.md)。[Inbox/队列与历史](inbox-queue.md)负责显式同步主号来信、待办管理和追溯，自身不触发读取。[粗读分流](triage.md)显式复用 Reader 轻预览，宿主判断并保存建议，不自动执行。[批量阅读](scroll-batch.md)仍是显式选中视频的独立读取队列，支持重放与确认续读，无账号也可读取本地材料，不改变首页或投递规则。`video_agent` / `video_memory` 是旧名；`run.ps1 agent ...` 仅为兼容入口。

```powershell
& 'D:\IA\apps\video-reader\scroll.ps1' status
& 'D:\IA\apps\video-reader\scroll.ps1' run --query '想了解的主题'
& 'D:\IA\apps\video-reader\scroll.ps1' memory '用户明确表达的兴趣' --kind preference
& 'D:\IA\apps\video-reader\scroll.ps1' memory --query '兴趣关键词'
& 'D:\IA\apps\video-reader\scroll.ps1' forget '记忆ID'
```

命令由 Agent 代为执行。CLI 单轮用临时 `codex exec --ephemeral`，沿用用户 Codex 模型及登录，不创建用户可见聊天。评估器不加载宿主技能或插件、不调用工具，默认 300 秒超时；失败留档，不换模型。Claude Code 的交互式选片直接用同一 MCP，不需要另一套核心或这个 Codex 执行器。

记忆采用标准库 SQLite + FTS5 trigram，位于 `data/agent/memory.sqlite3`，无需数据库服务或向量模型。兴趣、用户反馈与 Agent 观察分开，按账号隔离，可查、去重和删除。每轮 JSON 与简短 Markdown 在 `data/agent/rounds/<账号域>/<轮次>/`，引用共享媒体，不复制视频；缓存、预览、已读、已推荐分开。

### 单轮状态与显式恢复（2026-11-04）

```powershell
& 'D:\IA\apps\video-reader\scroll.ps1' status
& 'D:\IA\apps\video-reader\scroll.ps1' status 'round_轮次ID' --offline
& 'D:\IA\apps\video-reader\scroll.ps1' recover 'round_轮次ID'
```

MCP 对应 `scroll_round(action="status", run_id=...)` 和 `scroll_round(action="recover", run_id=..., dry_run=true)`。省略 run_id 的 status 保留日记录、任务执行器、发送账本和最近轮次。单轮查询另返回最近 100 条事件；完整历史保存在本地 SQLite 的 run_events，不因重试覆盖。

`runtime` 区分阶段、执行者、心跳与最近进展。OS 所有权锁判断执行者是否仍持有任务；心跳新鲜本身不证明活着。查询不等待单轮执行锁或视频材料锁。进程消失时投影为 interrupted，保留 recorded_status 和原始快照，不为了查询修改历史业务记录。旧轮次无阶段证据时明确显示 legacy_stage_not_recorded。

`checkpoint` 保存已准备预览、session 和已评估 URL；`artifacts` 指向材料、结果、归档和宿主日志。候选、单条预览和模型判断分别落盘。日记录在发现候选前即登记，异常退出后同日不重新取首页；旧数据缺少日索引时也先复用已登记的轮次。

recover 在原 run_id 内继续，复用候选、已保存预览和有效判断。缺少候选与预览时拒绝恢复，不能用新首页补成旧轮次。已完成结果只恢复归档；宿主旧日志和决策在后续调用前复制到 host/history。每次显式恢复记录原状态、错误与发送状态。

**恢复始终只留档，不发送。** CLI 不接受 recover --deliver，MCP 要求 dry_run=true。发送中断保留 sending 原记录，查询按账本显示 uncertain 或已确认的平台接受；不会改写成 not_sent。平台接受与实际收件仍分开。`resume` 继续仅用于解除平台请求暂停，与 recover 不同。

这是现有单轮工作流的状态与接续，不是 Inbox 或后台阅读队列。宿主选片判断也不等于完整阅读，checkpoint 的 full_reading_completed 保持 false。现有同步 Reader 深读关联 session；只有实际返回 job 时才登记 Reader job，不虚构独立任务。恢复可能需要重新调用宿主或补齐未就绪的原候选材料，不清除平台暂停、不切换模型。

CLI 可直接使用当前源码；已运行的 MCP 进程需重启连接加载新代码。验证范围与历史故障见[本批记录](../validation/scroll-state-20261104/report-source.md)。

### 私信与可选唤醒

主号 UID 已配置，三轮对话均已确认收件。推荐投递为简短合并消息及本地留档；Inbox 可显式同步授权主号来信，未启用常驻监听，不自动评论收藏。普通推荐自动投递与区间唤醒默认关闭；本机日试用是另行授权的策略，见[日试用运行说明](daily-trial.md)。`scroll.ps1 run` 默认不发信；显式 `--deliver` 还需 `agent.delivery.enabled=true`。接口接受不等于实际收件，失败或不确定的发送不自动重试。

`scroll.ps1 config --payload <UTF-8 JSON>` 只合并 agent 设置，不覆盖其他配置，也不注册后台任务。唤醒支持：

- `enabled`：默认 false。
- `mode=fixed` 配合 `interval_seconds`：固定等待间隔。
- `mode=range` 配合 `min_seconds` / `max_seconds`：每轮结束后在区间内选择等待时间。
- `windows=[{"start":"09:00","end":"22:00"}]`：允许时段，可跨午夜；空数组为全天。
- `timezone`：local、UTC 或 `+08:00` 等偏移；IANA 名称需要本机时区数据。

这些字段都位于 `agent.wake`。具体数值和启用状态须由用户指定，示例不是默认频率。启用后显式运行 `scroll.ps1 watch`，或外部触发 `scroll.ps1 tick`。上一轮未结束不并发，错过窗口不补跑；关闭配置后 watch 退出。区间唤醒未作为本机日试用的触发器；已注册的首页首条 Windows 任务由[日试用运行说明](daily-trial.md)维护。

### 材料与成本边界

新取数通道共享账号级磁盘缓存、请求间隔、每日计数和受限暂停。搜索的签名时间变化不破坏缓存；缺字幕、缺原生图均保留缺项。`--offline` 只保证 B 站材料离线，CLI 模型判断仍需宿主服务。

CLI 对材料不足的短片可调用既有 Reader 深读，默认最多 1 条、源时长不超过 300 秒，也可关闭。模型、登录与下载缓存不复制。B 站原生请求与 yt-dlp urlopen 已共用账号预算与暂停，底层重定向不另计，不能当作平台许可或免风控保证。原有推荐材料最多 200 段的摘录规则保持，带截断标记；完整学习使用 Reader 或批量队列读全。预览判断不替代全片校对、连续动作或原生声音理解。历史基线见 [0.7.0 记录](../validation/agent-0.7.0/report-source.md)，当前证据见 [0.10.0rc1](../validation/reader-0.10.0rc1/report-source.md)。
