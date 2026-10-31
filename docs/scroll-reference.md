# Scroll Agent 普通工作流参考

身份：共享安装 0.10.0rc2 的普通单轮、记忆和可选唤醒操作参考；本机每日首条策略、任务状态及依赖以[日试用运行说明](daily-trial.md)为准。

Scroll 消费 Reader 材料，负责个人账号流及记录。默认每轮 10 个候选、最多 3 条预览、最多推荐 2 条可配置。通用主题检索无需个人工作流。

当前 MCP 为 `scroll_round` / `scroll_memory` / `scroll_batch`，操作契约见 [Scroll Skill](../scroll-skill/SKILL.md)。[批量阅读](scroll-batch.md)是显式选中视频的独立队列，支持重放与确认续读，无账号也可读取本地材料，不改变首页或投递规则。`video_agent` / `video_memory` 是旧名；`run.ps1 agent ...` 仅为兼容入口。

```powershell
& 'D:\IA\apps\video-reader\scroll.ps1' status
& 'D:\IA\apps\video-reader\scroll.ps1' run --query '想了解的主题'
& 'D:\IA\apps\video-reader\scroll.ps1' memory '用户明确表达的兴趣' --kind preference
& 'D:\IA\apps\video-reader\scroll.ps1' memory --query '兴趣关键词'
& 'D:\IA\apps\video-reader\scroll.ps1' forget '记忆ID'
```

命令由 Agent 代为执行。CLI 单轮用临时 `codex exec --ephemeral`，沿用用户 Codex 模型及登录，不创建用户可见聊天。评估器不加载宿主技能或插件、不调用工具，默认 300 秒超时；失败留档，不换模型。Claude Code 的交互式选片直接用同一 MCP，不需要另一套核心或这个 Codex 执行器。

记忆采用标准库 SQLite + FTS5 trigram，位于 `data/agent/memory.sqlite3`，无需数据库服务或向量模型。兴趣、用户反馈与 Agent 观察分开，按账号隔离，可查、去重和删除。每轮 JSON 与简短 Markdown 在 `data/agent/rounds/<账号域>/<轮次>/`，引用共享媒体，不复制视频；缓存、预览、已读、已推荐分开。

### 私信与可选唤醒

主号 UID 已配置，三轮对话均已确认收件。产品只做简短合并推荐及本地留档，不监听私信，不自动评论收藏。普通推荐自动投递与区间唤醒默认关闭；本机日试用是另行授权的策略，见[日试用运行说明](daily-trial.md)。`scroll.ps1 run` 默认不发信；显式 `--deliver` 还需 `agent.delivery.enabled=true`。接口接受不等于实际收件，失败或不确定的发送不自动重试。

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
