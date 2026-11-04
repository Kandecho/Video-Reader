# Inbox、队列与历史

身份：2026-11-04 的个人收件与任务队列操作参考。Inbox 与原消息历史归 Scroll，通用队列与任务历史归 reading_tasks，见[任务参考](tasks.md)；这些操作不启动视频读取、模型消费或后台阅读，不调用旧 batch-next / run 来代替队列操作。另有显式授权的[粗读分流原型](triage.md)，不随同步自动触发。

## 当前规则

- 收件限于已配置主号发给组件小号的一对一私信。每次显式同步该会话，不扫描其他发送者，也不发送消息或设置会话已读。
- 首次同步登记启用时间。用户已选择：**旧消息只保留历史；启用后的新视频在同步时自动入队。** 本机启用界线为北京时间 2026-11-04 13:51:00，持久状态是准绳，重启或重试不重置。
- 当前通过会话主动同步，没有轮询服务或新定时任务。新消息须经过下一次同步才进入本地历史/队列；原 20:00 首页首条日试用继续独立运行。
- 默认按收件时间排队；可置顶、调优先级、暂停、恢复、人工完成、取消或归档。所有变动留事件历史，不删除原消息。
- 同一私信重复同步不重复建任务。新消息与现有待办的来源及任务相同则关联同一项，保留每条原消息；同一视频带不同要求则分别入队。已完成项不作为全局 BV 去重规则。

## 在会话中使用

可以直接说“同步收件箱”“看看待办”“把这条放前面”“先暂停这条”“查一下之前的任务/原消息”。Agent 用下方工具操作；不是执行私信中自带的指令。

| 需要 | MCP |
|---|---|
| 查收件状态 | `scroll_inbox(action="status")` |
| 同步主号来信 | `scroll_inbox(action="sync")` |
| 查消息历史 | `scroll_inbox(action="history", query="关键词")` |
| 查看原消息 | `scroll_inbox(action="history", message_id="im_...")` |
| 把旧视频明确加入待办 | `scroll_inbox(action="enqueue", message_id="im_...", video_index=0, task="可选的新要求")` |
| 查看待办 | `scroll_queue(action="list")` |
| 查询其他状态/全部 | `scroll_queue(action="list", state="all")`；也可单独查 paused/done/cancelled/archived |
| 查看某项、原消息关联和已有材料 | `scroll_queue(action="show", item_id="q_...")` |
| 手动入队 | `scroll_queue(action="add", source="BV 或视频链接", task="具体要求")` |
| 放到最前 | `scroll_queue(action="first", item_id="q_...")` |
| 修改状态或任务 | `scroll_queue(action="update", item_id="q_...", state="paused", reason="稍后处理")` |
| 查询操作历史 | `scroll_queue(action="history", item_id="q_...")`，省略 item_id 查全局事件 |

更新支持 expected_revision，避免覆盖较新的操作。手动 add 的 new_task=true 明确新建独立任务；普通同来源、同任务的活动项会返回重复提示及既有 item_id。修改 task 留下前后版本，原私信不改。

`pending` 是待办，`paused` 是暂停，`done` 是用户/会话明确人工标记完成，`cancelled` 是取消，`archived` 是归档。暂停项须显式改回 pending 才能置顶。人工 done 不证明 Reader 已读取、宿主已理解或校对通过；当前没有自动消费、processing 状态或结果生成。

## CLI

```powershell
& 'D:\IA\apps\video-reader\scroll.ps1' inbox-sync
& 'D:\IA\apps\video-reader\scroll.ps1' inbox-status
& 'D:\IA\apps\video-reader\scroll.ps1' inbox-history --query '关键词' --limit 20
& 'D:\IA\apps\video-reader\scroll.ps1' inbox-history 'im_消息ID'
& 'D:\IA\apps\video-reader\scroll.ps1' inbox-enqueue 'im_消息ID' --index 0 --task '明确要求'
& 'D:\IA\apps\video-reader\scroll.ps1' queue-add 'BV1E1421t7m2?p=2' --task '关注第二P'
& 'D:\IA\apps\video-reader\scroll.ps1' queue-list
& 'D:\IA\apps\video-reader\scroll.ps1' queue-first 'q_任务ID'
& 'D:\IA\apps\video-reader\scroll.ps1' queue-update 'q_任务ID' --state paused --reason '稍后处理'
& 'D:\IA\apps\video-reader\scroll.ps1' queue-update 'q_任务ID' --state pending
& 'D:\IA\apps\video-reader\scroll.ps1' queue-history 'q_任务ID'
```

queue-update 还支持 --priority、--task、--revision，或 --payload 指定 UTF-8 JSON 的 state/priority/task/reason/expected_revision。queue-list 的 --state all 查全部。各历史/列表命令用 --cursor 继续 next_cursor；--limit 默认 20，范围 1–100。旧 `run.ps1 agent ...` 桥保留同样操作。Inbox/队列命令不接受 --deliver；inbox-sync 不接受 --offline，其余查询不会构造网络 Platform。

## 同步、分页与保存

默认每次最多 3 页，每页 50 条会话消息。MCP 的 max_pages/page_size 或 CLI 的 --max-pages/--page-size 可在 1–10 页、1–100 条内调整。预算和暂停继续使用组件原网络通道，退出不清零。

同步先查新消息，再补历史；新消息突增导致的缺口也保存上界、下界和续传游标。partial 表示还有已登记的范围待继续同步，不能当作全量。每一页的消息、自动入队及游标在同一个 SQLite 事务提交；失败保留已提交成果和原因，下次显式同步继续。空页却声称有后页或游标不推进时保留缺口，不宣称结束。

原始消息键以文本保存，保全来源、序列、时间、类型、正文、解析结果和原始 JSON。按 message_id 查询包含最近 100 条修订的前后版本，完整事件继续保存在库中；任务历史也包含关联消息的修订。已建任务不因原消息变化静默删除，查看时会提示当前来源状态。平台未返回的删除/隐藏或历史消息不作完整承诺。

文字支持 BV、B 站视频/分 P、b23 短链和 YouTube 链接；原生视频分享卡片保留标题与卡片附言。不获取视频元数据、展开短链、转写或取帧。短链与 AV 身份暂按原链接保存，不声称与另一 BV 已完成别名归并。其他消息及解析失败均留在历史，不强行当视频任务。

同一文字消息中的附言随视频保存。独立文字消息留在历史，不擅自归给相邻的视频；需要时由会话明确修改 task。已有本账号缓存 session 和同视频任务会作为提示返回，缓存存在不推定已读。

队列分页绑定当前排序修订，列表期间发生变动会明确要求重查；消息历史按原会话序列倒序，补历史不改变新旧顺序；不可变事件历史采用游标续读，追加事件不覆盖旧页范围。

## 存储与边界

复用 `data/agent/memory.sqlite3`，新增 inbox_feeds、inbox_messages、queue_items、queue_links、queue_events、queue_meta，任务使用稳定库身份，Inbox 按来源账号隔离。旧推荐、日轮、发送账本和校对不改。查通用任务/历史不需要登录；材料获取仍按对应来源账号授权。查询不验证登录或清除暂停。

CLI 立即使用当前源码。已运行的 MCP 连接需重启，加载 scroll_inbox / scroll_queue 及后续的 scroll_triage；Scroll 共 7 个工具，Reader 为 20 个。旧消息历史游标新增来源账号绑定，旧游标失效时重新查询。当前未增加调度或前端。收件实测与限制见[原批验收](../validation/inbox-queue-20261104/report-source.md)。
