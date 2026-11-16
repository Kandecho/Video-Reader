# 通用阅读任务 队列与历史

身份：2026-11-14 任务字段与正式目录同步后的操作入口。实现位于 reading_tasks，供会话、Reader 与 Scroll 适配器共用；不依赖个人偏好或 B 站登录才能管理本地任务。

## 职责

先按[工作流契约](workflow-contract.md)区分材料、处理记录、任务与处置：视频、讨论及既有笔记可反复使用；获取、读取、取帧、分包等过程不自动成为任务。边界明确的目的才是任务，完成按问题、核查、试用、翻译、收藏或学习整理等约定验收；三档留存不决定交付内容。

任务模块负责队列、原附言与 comment/request、来源引用、分流、批量消费进度、结果及事件。Reader 负责材料和处理 job；Scroll 负责私信 Inbox、原消息与同步历史、偏好、推荐和发信。两种历史有可追溯的引用，任务查询不联查 Inbox 私有表。

同视频可有不同任务，task ID 与材料 ID 不互换。state固定，task_type按新增前优先复用原则维护，task_description说明具体工作；主筛选只取原任务状态与类型。done表示任务已完成，也可包含用户明确确认的终止，completion_method保留该方式；latest_result保存产物及范围，不把下载、交付、缓存或终止推为视频已读或已核查。

## 入口

Reader MCP 新增 `video_tasks(action, item_id, parameters_json)`。action 使用下表完整名称，parameters_json 为 JSON 对象字符串。Scroll 的旧 queue/triage/batch 工具与 CLI 保留为兼容适配器，不再拥有这些通用业务实现。

| 需要 | action / 参数 |
|---|---|
| 查待办或全部 | queue-list；`{"state":"all"}` |
| 查任务、附言和结果 | queue-show；item_id=q_... |
| 手动入队 | queue-add；item_id 为 BV、视频链接或绝对本地文件路径，task/title及task_type/task_description可选 |
| 调整与置顶 | queue-update / queue-first；state、priority、task、task_type、task_description、completion_method、reason、revision；核心字段可由payload维护 |
| 复用任务类型 | queue-list返回task_types，包含当前任务库已用及历史名称；同一目的优先沿用，类型不是固定枚举 |
| 操作历史 | queue-history；item_id 可省，limit/cursor 续读 |
| 保存任务产物 | queue-result；result 含 summary、artifacts 路径列表、task_scope 和覆盖说明；complete=true 才明确完成 |
| 粗读与分流 | triage-prepare/material/content/submit/show/history；见[参考](triage.md) |
| 显式批读 | batch-start/next/status/retry；见[参考](scroll-batch.md) |
| 查历史产物与正文 | queue-search；query/limit/cursor，见[材料回查](content-index.md) |
| 本地总目录及批次投影 | catalog-build/status/update；见[总目录](master-catalog.md)；成果登记后自动刷新已启用目录 |
| 任务处置与留存决定 | followup-save/list兼容入口；保存处置状态、自由描述、原因、备注及文件，不必是另一个或后发任务；见[目录参考](master-catalog.md) |
| 单条宿主消费 | run-start；item_id 为 pending 任务，参数见下节 |
| 查状态与中断接续 | run-status / run-resume；item_id 为 r_... |
| 局部视觉短会话 | visual-start；item_id 为 v_...，见下节；visual-show 查文字记录，visual-frame 显式回看原图 |

CLI 无需 Scroll 入口：

```powershell
& 'D:\IA\apps\video-reader\tasks.ps1' queue-list --state all
& 'D:\IA\apps\video-reader\tasks.ps1' queue-add 'D:\Videos\example.mp4' --task '提取项目想法'
& 'D:\IA\apps\video-reader\tasks.ps1' queue-add 'BV1E1421t7m2' --task '学习一下' --task-type '整理笔记' --task-description '整理职责拆分的原则、代码示例与限制'
& 'D:\IA\apps\video-reader\tasks.ps1' queue-show 'q_任务ID'
& 'D:\IA\apps\video-reader\tasks.ps1' queue-result 'q_任务ID' --payload 'D:\Results\result.json' --complete
```

result.json 示意：

```json
{"title":"项目简报","summary":"整理能力和复用条件","task_scope":"用户明确要求的范围","artifacts":["D:/Results/notes.md"],"full_video_verified":false}
```

产物须实际存在，保存时计算 SHA-256。结果追加历史，不覆盖原消息。原 task 保留兼容；note 包含 original、kind、comment、request。修改 task 后旧意图不再冒充有效，旧分流会显示 stale。

## 核心字段与空值维护

`state`固定为pending／paused／done／cancelled／archived且不得为空。`task_type`和`completion_method`为最多200字符的可选短文本，`task_description`为最多4000字符的可选具体工作描述。类型先看 `queue-list.task_types` 再复用或新增，不按保存目录自动建类型。

核心字段由 `queue-add/update` 的显式参数或payload对象维护，CLI对应 `--task-type`、`--task-description`、`--completion-method`。为明确表达清空，推荐JSON payload；`catalog-update`收到这些核心字段时也分流到任务更新，其余值仍是呈现注记。`result.catalog`中的旧task_goal/task_description只兼容历史，不能覆盖核心字段。

| 更新输入 | 含义 |
|---|---|
| 不包含该字段 | 保留当前值 |
| 可选文本为null、空字符串或纯空白 | 清空为null |
| purposes、tags或处置artifacts为[] | 清空对应列表，不用文本“无”代替 |
| 状态或处置description为null | 拒绝；这两类值必填 |

界面“未注明／未填写”不写进字段。明确清空后不再由标题、原task或旧目录标签恢复。新建时只有描述未传才允许旧非空task初始化描述；显式null仍为空。原话与新描述分别保留，修改前后进历史，修订冲突明确失败。

例如 `queue-update` 的payload可为 `{"task_type":null,"task_description":"整理指定问题的论据与局限"}`，只清空类型并更新描述。已确认终止时使用 `{"state":"done","completion_method":"终止","reason":"用户确认来源下架，结束获取；未读取视频或核查主张"}`。完成方式只在done时非空，离开done自动清空；不用默认文案填满可选字段，也不把所有cancelled批量视为完成。

处置记录通过 `followup-save/list`保存。例如已回答问题、已存入KIBRARY、无新增认识不另存都可属于同一整理／问答任务。副本必须实际保存核对；明确不另存可done且artifacts=[]。可选reason／notes留空用null，未传则保留。未知处置不是待办，未请求的步骤不自动生成任务。

只需回答问题时，直接答复本身就是成果：result可传 `answer:{question,text,status:"answered"|"partial",limitations?,basis?}`，artifacts可空；仍保存summary、task_scope及实际覆盖。问题、直接答案、理由和局限优先呈现，不以泛泛视频摘要或长笔记代替回答。partial不能配complete=true；不把回答任务完成当全片核验。

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

`video_tasks(action="run-start", item_id=TASK_ID, parameters_json=...)` 显式处理一条pending任务，默认使用canonical task_description；描述为空时必须显式提供具体request。source默认auto，context_files可附已授权的Markdown／文本参考，wait_seconds默认1。也可用tasks.ps1的run-start --payload request.json。此入口不启动常驻消费者、私信监听或调度，不发送汇报。

领取保存 run_id、原任务语义、来源与材料绑定。目录、语音处理与正文交付不是读完证据；真正的临时宿主收到原文及图片后，返回匹配的 packet_id、完整观察 ID 和实际笔记，才保存观察检查点。仅靠 job 完成或附件发送不会标记任务完成。

按包保留原文、源时间、图片附件及哈希、宿主原始输出和 accepted 记录。关键补证请求需处理或明确保留未完成，不能跳过。单包已有成文内容直接复用，不增加无必要的整理调用；多包最后整理已观察笔记。结果保存实际 Markdown、覆盖范围、未核定事项和完成依据，full_video_verified 保持独立。

2026-11-09 的真实检验后，消费上下文协议更新为 2（run-status 的 context_contract_version）。初读和补证各自追加保存；补证只发送请求时间附近的完整原段、必要邻句、新图及已接受证据记录，不再发送整包原文、整篇旧笔记或项目参考全文。单包发生补证时也会合并整理，不能把局部补丁直接当作最终笔记。

后包复用带来源时间、段/帧引用的已接受证据记录，保留任务相关原句和代码。历史图像仅以记录引用，不重新附图，也不能冒作本次观察。上下文参与 packet_id 绑定；被暂停或修订拒绝的检查点不进入后包。补证中断后保持 pending_read，恢复只重试未接受的补证。

每项疑点有稳定 ID。终稿须逐项保留或引用具体观察记录说明解决依据，不能因为“已经读全”就清除识别或外部核查疑点；分包原始局限和处理决定留在 accepted 记录与运行检查点，面向用户的笔记使用整项任务的范围。旧记录可从已提交观察指向的初读 accepted 恢复，缺失原文件时明确报错；旧的已完成结果不改写。context_contract_version 表示当前加载的实现，历史结果仍为原快照。

run-status 只查询。失败/中断后显式 run-resume 原 run_id；已接受的包不重读，未接受的包重新尝试。每次宿主尝试有独立目录，旧进程迟到输出不能覆盖新尝试。并发重复启动复用同一领取；活跃 run 的 resume 不覆盖新检查点。

运行中暂停、取消或修改canonical任务描述会阻止旧结果继续或完成任务，提交使用语义身份及修订校验；原正式要求和描述快照保留。结果记录与run完成在同一数据库事务中幂等落盘；提交后worker中断不会重复追加结果。refresh=true只在原执行已结束后显式建立新run，旧superseded run不得恢复或提交；启动尚未确认时先恢复／查询原run。

宿主沿现有配置和本机 Codex CLI 调用；日志保留超时/传输原因，不自动改模型、供应商或平台账号。配置、模型额度和来源平台请求预算是不同限制。

### 定向问题按块消费（2026-11-09）

默认仍读取全部时间块。局部问题可以先通过 `video_content` 的 index/query/storyboard 确定相关块与必要邻域，再将同一目录的 `index_id`、非空 `block_ids` 一起传给 run-start。source 必须与建立目录时一致；自定义块长、语音上下文和修订从目录绑定复用。MCP parameters_json 或 CLI `--payload` 的 JSON 示例：

```json
{"request":"解释选定段落中的任务恢复机制","source":"auto","index_id":"ci_实际返回的ID","block_ids":["ci_实际返回的ID:5","ci_实际返回的ID:6"]}
```

这一路径复用已就绪的完整原段和已有图像，不补转写未选尾部。块内既没有原文也没有图像时，先用 Reader 的局部 transcript/read 补材料，再建立新目录。字幕缺口、近似分镜和未选部分均保留；词法命中不自动决定选块，完整笔记不能悄悄改成局部阅读。关键画面仍可由宿主请求补证。

run-status 与结果 coverage 的 reading_scope 区分本次计划块数、整个目录块数、未选块数和语音处理缺口；continuation 给出重返全目录的参数。未选块没有被标记成已观察。独立宿主必须明确返回 task_satisfied；材料不足时保存草稿、任务 pending，不能仅因选中块读完就完成整项要求。需要扩大选块时显式刷新已停止的 run，或为新的追问建任务；普通 run-resume 保持原选择和已接受的检查点。

### 耗时与尝试记录

每次实际调用宿主前，在该 run 的 attempts 子目录写入 metrics.json，记录 attempt/packet 关联、提示词字节数、所附图像的 ID、SHA-256、尺寸和文件字节。结束时保存耗时、返回或失败状态及 CLI 日志实际报告的 input/cached_input/output tokens。配置未指定模型时 configured_model 为 null，不把它推定成某个实际模型。

run-status 和结果 coverage.metrics 汇总已测尝试、失败、同包重复、准备耗时、整项经历时间和第一个已接受包的时间。重试不丢旧尝试；旧 run 未测的尝试单列 unmeasured_attempts。已知用量可为小计，usage_complete=false 时不可当总账；缺失字段是 null。返回成功和观察被接受分别计数。

这些是本地调用观测，不能测量宿主内部请求数、图像上下文重复次数或实际首次可用答案时间，上述字段保持未知。首个包被接受不代表答案已充分，包数下降也不直接证明全任务更快或事实质量不变。

## 局部视觉短会话（2026-11-09）

需要独立宿主查看局部画面、向主会话返回文字证据时，使用 `video_tasks(action="visual-start", item_id=SESSION_ID, parameters_json=...)`。先取得同一已打开会话的有效内容目录 index_id；一次指定 1–6 帧，时间须在视频范围内，width 默认 1920（64–3840），region 是归一化的 `[left,top,right,bottom]`。参数示例：

```json
{"index_id":"ci_实际返回的ID","request":"逐字记录画面中的方法签名，并说明图中依赖关系","frames":[{"timestamp_seconds":397,"width":1920}],"wait_seconds":1}
```

返回 job_id 后，用 `video_job(action="status"/"result", job_id=ID)` 轮询同一任务。每次观察使用既有宿主配置启动新的独立调用，只附本次源图，不转写语音，不改队列或发送。结果只有文字及元数据：screen_text、visual_observation、inference 分开，保留观察者、来源/分 P、时间、帧 ID、像素 SHA-256、尺寸、区域、材料与校对修订、疑点和 task_satisfied。主会话应说明依据来自独立宿主的观察记录，不能声称自己亲眼看过原图；采样观察也不是连续覆盖或完整校对。

后续追问可传 `prior_observation_ids`，最多 4 条同目录、同修订且仍有效的观察。它们只提供文字与来源引用，不重新附旧图；缺证时另发局部观察。`visual-show` 的 item_id 为 observation_id，返回保存记录及 current_material_valid；旧材料失效时仍可查历史，但不能把失效记录作为新观察的 prior。显式回看使用记录中 image_refs.revisit 的 `visual-frame` 参数（item_id 为 observation_id，index 为零基图像序号），交付当时冻结的原像素与裁剪，须实际查看；材料变更或像素哈希不符会拒绝回看。

此入口避免向主会话交付新的原图，不能清除主聊天已有图片。尝试耗时、附件身份和已报告用量保留；宿主内部请求的图片重放次数仍未知，不能仅据隔离或缓存宣称提速或节省。

## 后台许可与任务完成（阶段 6）

自动调度沿用同一 Consumer，后台专用许可、每日启动数、宿主尝试数和暂停策略归 reading_tasks.control；Scroll 只接收件和定时触发。手动 run-start 不受后台全局暂停影响，仍须遵守任务状态。资源未知等待，模型余额未知不伪装为充足；本地上限和额度错误暂停见[后台控制](background-consumption.md)。

入队检查与队列执行/恢复各有入口、计时、锁和调度；模型临时错误短间隔最多自动重试 2 次，复用原 run / 任务名额，新模型尝试另计；其它错误与 needs_attention 待检查。background-retry 接收 run_id，可显式接续失败任务，不同步 Inbox，也不消耗或重置自动重试次数。强制终止的 worker 恢复前核对并停止原尝试遗留的宿主进程，保留已接受包。同一 run 的 result 仍只提交一次。暂停后恢复之间的晚回包也不能推进检查点。

真实宿主返回 task_satisfied；如外部事实核查或寻找原版尚未完成，保存有用草稿与覆盖缺口，run 为 needs_attention，任务仍 pending，不重复自动领取。查看产物与补查范围后再明确修订要求或接续；不能为清空队列标记 done。
