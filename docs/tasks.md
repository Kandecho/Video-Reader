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

显式请求发送后才使用 `action="send"`，并要求既有 delivery.enabled 授权。CLI `scroll.ps1 report` 预览；`report-send --deliver` 发送。它与旧日轮共用发送接口和幂等账本，已接受或结果不确定的同一汇报不重发。同步收件不自动发送回执，本批没有新增调度。

收件白名单为 agent.inbox.sender_uid。旧投递收件人只在迁移时钉住一次；以后改投递对象不改变收件白名单。
