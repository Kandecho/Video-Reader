# 通用阅读任务 队列与历史

身份：2026-11-04 架构修复后的操作入口。实现位于 reading_tasks，供会话、Reader 与 Scroll 适配器共用；不依赖个人偏好或 B 站登录才能管理本地任务。

## 职责

任务模块负责队列、原附言与 comment/request、来源引用、分流、批量消费进度、结果及事件。Reader 负责材料和处理 job；Scroll 负责私信 Inbox、原消息与同步历史、偏好、推荐和发信。两种历史有可追溯的引用，任务查询不联查 Inbox 私有表。

同视频可有不同任务，task ID 与材料 ID 不互换。done 表示明确完成了任务；latest_result 保存产物及覆盖范围，不把下载、交付或缓存存在推为完整阅读。

## 入口

Reader MCP 新增 `video_tasks(action, item_id, parameters_json)`。action 使用下表完整名称，parameters_json 为 JSON 对象字符串。Scroll 的旧 queue/triage/batch 工具与 CLI 保留为兼容适配器，不再拥有这些通用业务实现。

| 需要 | action / 参数 |
|---|---|
| 查待办或全部 | queue-list；`{"state":"all"}` |
| 查任务、附言和结果 | queue-show；item_id=q_... |
| 手动入队 | queue-add；item_id 为 BV、视频链接或绝对本地文件路径，task/title 可选 |
| 调整与置顶 | queue-update / queue-first；state、priority、task、reason、revision |
| 操作历史 | queue-history；item_id 可省，limit/cursor 续读 |
| 保存任务产物 | queue-result；result 含 summary、artifacts 路径列表、task_scope 和覆盖说明；complete=true 才明确完成 |
| 粗读与分流 | triage-prepare/material/content/submit/show/history；见[参考](triage.md) |
| 显式批读 | batch-start/next/status/retry；见[参考](scroll-batch.md) |
| 查历史产物与正文 | queue-search；query/limit/cursor，见[材料回查](content-index.md) |
| 单条宿主消费 | run-start；item_id 为 pending 任务，参数见下节 |
| 查状态与中断接续 | run-status / run-resume；item_id 为 r_... |

CLI 无需 Scroll 入口：

```powershell
& 'D:\IA\apps\video-reader\tasks.ps1' queue-list --state all
& 'D:\IA\apps\video-reader\tasks.ps1' queue-add 'D:\Videos\example.mp4' --task '提取项目想法'
& 'D:\IA\apps\video-reader\tasks.ps1' queue-show 'q_任务ID'
& 'D:\IA\apps\video-reader\tasks.ps1' queue-result 'q_任务ID' --payload 'D:\Results\result.json' --complete
```

result.json 示意：

```json
{"title":"项目简报","summary":"整理能力和复用条件","task_scope":"用户明确要求的范围","artifacts":["D:/Results/notes.md"],"full_video_verified":false}
```

产物须实际存在，保存时计算 SHA-256。结果追加历史，不覆盖原消息。原 task 保留兼容；note 包含 original、kind、comment、request。修改 task 后旧意图不再冒充有效，旧分流会显示 stale。

## 库身份与存储

tasks.directory 默认 data/tasks，library.json 保存稳定的库 ID 与数据库位置。tasks.database / tasks.library 可以显式指定。首次兼容已有安装时，继续使用原 memory.sqlite3，不搬动或重建数据；原账号键保留为不透明库 ID，此后不随登录改变。

SQLite 连接归 Store；Memory 只初始化个人业务表。Queue 只创建任务、来源快照、意图、结果和事件表；Inbox 创建自己的消息、同步与事件表。共用同一 SQLite 文件时，消息、入队、来源关联和同步游标仍可在一个事务提交。

旧原消息与旧事件保留，legacy 适配器一次性导入任务所需的来源快照和已保存意图。新任务来源不要求采用私信结构。材料目录由 Reader 的公开 materials 接口查询，账号权限与任务库身份分开；缺少登录不妨碍查待办，也不授权读取另一账号的受限材料。

批读旧路径仍可继续，新批次保存至任务目录；其材料账号绑定继续保留。查询任务结果、初步分流与实际阅读进度是不同操作。

## 与 Scroll 发信联通

`scroll_report(action="preview", item_ids_json="[...]")` 生成本地汇报，可用 message_id 查关联任务。内容区分是否已关联入队、初步分流、当前状态和产物。没有本地关联时只报告“尚未找到关联任务”，不推断平台是否收到消息。

显式请求发送后才使用 `action="send"`，并要求既有 delivery.enabled 授权。CLI `scroll.ps1 report` 预览；`report-send --deliver` 发送。它与旧日轮共用发送接口和幂等账本，已接受或结果不确定的同一汇报不重发。同步收件不自动发送回执。另行授权的[后台调度](background-consumption.md)不经发送通路。

收件白名单为 agent.inbox.sender_uid。旧投递收件人只在迁移时钉住一次；以后改投递对象不改变收件白名单。

## 单条宿主消费（本地阶段 4）

`video_tasks(action="run-start", item_id=TASK_ID, parameters_json=...)` 显式处理一条 pending 任务。无原要求时必须提供 request；source 默认 auto，context_files 可附已授权的 Markdown/文本参考，wait_seconds 默认 1。也可用 tasks.ps1 的 run-start --payload request.json。此入口不启动常驻消费者、私信监听或调度，不发送汇报。

领取保存 run_id、原任务语义、来源与材料绑定。目录、语音处理与正文交付不是读完证据；真正的临时宿主收到原文及图片后，返回匹配的 packet_id、完整观察 ID 和实际笔记，才保存观察检查点。仅靠 job 完成或附件发送不会标记任务完成。

按包保留原文、源时间、图片附件及哈希、宿主原始输出和 accepted 记录。关键补证请求需处理或明确保留未完成，不能跳过。单包已有成文内容直接复用，不增加无必要的整理调用；多包最后整理已观察笔记。结果保存实际 Markdown、覆盖范围、未核定事项和完成依据，full_video_verified 保持独立。

run-status 只查询。失败/中断后显式 run-resume 原 run_id；已接受的包不重读，未接受的包重新尝试。每次宿主尝试有独立目录，旧进程迟到输出不能覆盖新尝试。并发重复启动复用同一领取；活跃 run 的 resume 不覆盖新检查点。

运行中暂停、取消或改要求会阻止旧结果完成任务，提交使用修订校验。结果记录与 run 完成在同一数据库事务中幂等落盘；提交后 worker 中断不会重复追加结果。refresh=true 只在原执行已结束后显式建立新 run，旧 superseded run 不得恢复或提交；启动尚未确认时先恢复/查询原 run。

宿主沿现有配置和本机 Codex CLI 调用；日志保留超时/传输原因，不自动改模型、供应商或平台账号。配置、模型额度和来源平台请求预算是不同限制。

## 后台许可与任务完成（阶段 6）

自动调度沿用同一 Consumer，后台专用许可、每日启动数、宿主尝试数和暂停策略归 reading_tasks.control；Scroll 只接收件和定时触发。手动 run-start 不受后台全局暂停影响，仍须遵守任务状态。资源未知等待，模型余额未知不伪装为充足；本地上限和额度错误暂停见[后台控制](background-consumption.md)。

入队检查与队列执行/恢复各有入口、计时、锁和调度；模型临时错误短间隔最多自动重试 2 次，复用原 run / 任务名额，新模型尝试另计；其它错误与 needs_attention 待检查。background-retry 接收 run_id，可显式接续失败任务，不同步 Inbox，也不消耗或重置自动重试次数。强制终止的 worker 恢复前核对并停止原尝试遗留的宿主进程，保留已接受包。同一 run 的 result 仍只提交一次。暂停后恢复之间的晚回包也不能推进检查点。

真实宿主返回 task_satisfied；如外部事实核查或寻找原版尚未完成，保存有用草稿与覆盖缺口，run 为 needs_attention，任务仍 pending，不重复自动领取。查看产物与补查范围后再明确修订要求或接续；不能为清空队列标记 done。
