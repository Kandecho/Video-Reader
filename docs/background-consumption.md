# 后台收件与阅读

2026-11-07 当前状态：按用户要求，后台收信已关闭（sync_enabled=false，Inbox Intake 触发器禁用）。手动链接/BV读取和明确要求的单次 Inbox 同步照常可用；队列执行/重试仍每 5 分钟检查。只向小号转发视频不会再被定时检测入队。下述 60 分钟是保留参数，不表示当前仍在收信。

用户最新确认：北京时间 09:00–23:00 不变，入队检测每 60 分钟；队列执行与恢复独立，每 5 分钟检查。模型连接超时等临时错误等待短间隔后，最多自动重试 2 次。每天最多启动 3 条、同时最多 1 条后台阅读；额度不足暂停阅读。

检查收件、队列、时段和资源由脚本完成，不调用模型；允许阅读时才启动现有宿主。只有用户明确启用才会运行，安装插件、同步 Inbox 或查询状态均不会自行启用。电脑需开机且当前 Windows 用户保持登录，锁屏可运行，注销或休眠期间不运行。

## 两路独立运行

| 入口 | 当前间隔 | 工作与边界 |
|---|---|---|
| intake / background-intake | 60 分钟 | 仅同步已配置主号到组件小号会话、保留原消息并入队；不读片、不调用模型 |
| queue / background-queue | 5 分钟 | 只处理本地任务的执行、等待恢复及有限重试；不检查私信 |
| retry / background-retry | 用户明确调用 | 重试指定失败 run，沿用原要求、检查点和许可；不检测入队 |

两路分别保存上次检查、结果，并使用独立锁和 Windows 触发器。收件失败、未到收件时间、模型额度阅读暂停，都不阻止另一条允许运行的通路。tick / background-tick 是兼容入口，依次调用两路；一边报错不阻止另一边。

同卡片附言仍按原规则入队。独立文字不自动关联相邻视频；本次三对仅因用户明确确认才写入。没有具体要求、标为评论或意图不明的任务保留待办，不调用模型猜要求。不发送回执或结果消息。

## 查询与控制

MCP：`scroll_background(action="status|config|pause|resume|intake|queue|retry|tick|hold", parameters_json="{}")`。已有 MCP 连接需重启加载新动作；CLI 立即使用当前源码。

```powershell
& 'D:\IA\apps\video-reader\scroll.ps1' background-status
& 'D:\IA\apps\video-reader\scroll.ps1' background-intake
& 'D:\IA\apps\video-reader\scroll.ps1' background-queue
& 'D:\IA\apps\video-reader\scroll.ps1' background-retry --payload 'D:\Results\retry.json'
& 'D:\IA\apps\video-reader\scroll.ps1' background-pause
& 'D:\IA\apps\video-reader\scroll.ps1' background-resume
& 'D:\IA\apps\video-reader\scroll.ps1' background-hold --payload 'D:\Results\hold.json'
```

retry.json 为 `{"run_id":"r_原执行ID"}`。显式重试不受“最多 2 次自动重试”限制，也不重置自动次数；仍受任务状态、时段、资源、暂停及每日/单 run 宿主调用上限控制。不会因前台忙而消耗自动重试次数。

hold.json 为 `{"minutes":60}`，让后台阅读等待一小时；`{"minutes":0}` 解除。pause 暂停本功能；resume 不清除来源平台暂停、不切换模型或登录。read_enabled=false 允许收件但不读片，enabled=false 关闭本功能。既有 20:00 日推保持独立。

status 提供 policy、两路 last_intake_tick / last_queue_tick 与结果、暂停原因、今日启动数、宿主尝试数、pending_retries、活动 run、缺要求及需补查任务。查询不收件、不调用模型。产物与进度继续用 [queue-show / run-status](tasks.md) 查询。

## 配置来源与 Windows 调度

同一后台策略是运行时与 Windows 触发器的参数来源。通过 background-config --payload JSON 修改：

```json
{"intake_interval_minutes":60,"queue_interval_minutes":5,"max_host_retries":2,"window_start":"09:00","window_end":"23:00","timezone_offset_minutes":480}
```

旧 interval_minutes 作为兼容别名同时设置两路，不能与新间隔字段混传。旧数据库按已有值迁移，不重置每日上限或历史；本次再按用户新要求改成 60 / 5。

```powershell
& 'D:\IA\apps\video-reader\tools\manage_scroll_background.ps1' -Action Plan
& 'D:\IA\apps\video-reader\tools\manage_scroll_background.ps1' -Action Install
& 'D:\IA\apps\video-reader\tools\manage_scroll_background.ps1' -Action Status
& 'D:\IA\apps\video-reader\tools\manage_scroll_background.ps1' -Action Remove
```

Plan 只预览从策略生成的时段、时区与两路间隔，不访问 Windows 调度器。先 config 改参数，再 Install 重建触发器；调度脚本不再写死 09:00 或 14 小时。旧 Install -IntervalMinutes 仍是兼容覆盖，会同时更新两路，日常应使用新配置字段。

任务为 `Video Reader Inbox Intake`（-Mode Intake）和 `Video Reader Task Queue`（-Mode Queue），共用 tools/run_scroll_background.ps1。迁移只移除核对过入口的旧合并任务 `Video Reader Inbox Queue`，不覆盖同名不同入口，不改首页首条日推。使用当前用户 Interactive / Limited，不存系统密码。日志分别在 data/agent/background-task/intake 与 queue；数据库保存许可、计数与事件。

2026-11-07 修正空控制台闪现：任务先用同一 Python 安装中的 GUI `pythonw.exe` 进入 tools/run_scheduled_hidden.py，再以 CREATE_NO_WINDOW 启动原 PowerShell runner。安装时检查 PE 子系统，避免误用本机虚拟环境中仍为控制台程序的同名 shim。仅用 `pwsh -WindowStyle Hidden` 在本机实测仍会弹出约 1 秒的 Windows Terminal。启动层错误另记 data/agent/scheduler/*.log，原业务日志与退出码保留。更新现有任务仅替换 Action；Inbox Intake 仍禁用。重装脚本也保留已有禁用状态。

## 等待、重试与真实完成

CPU 超过 85%、可用内存少于 2048 MB、资源探测失败或 Reader 有其它活动 job 时，阅读等待。宿主调用期间每秒检查暂停、时段、临时等待和 Reader 活动任务，必要时停止自己的模型进程。它无法识别整个桌面或所有聊天的忙闲，需要主动留余量时用 hold/pause。

模型账户剩余额度仍未知。每日 3 条是用户授权的本地上限，另保守限制每日 60 次、单 run 20 次宿主尝试；它们不是供应商余额。每次调用前记账，超时和中断不退回。额度错误锁定 model_quota 阅读暂停，明确恢复后才继续，纯脚本入队检测可继续。

Windows 上，后台 CLI 子进程会继承已启用的系统代理；显式 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY（包括空值）优先，NO_PROXY 保留，不修改系统或父进程环境。11 月 6 日的超时/工作区路由失败已定位到这处遗漏，补齐后原模型真实读图成功。[诊断结论](../validation/host-route-20261106/report-source.md)。

仅 host_timeout / host_transport 类临时错误自动短间隔重试，最多 2 次；失败完成后等待约 5 分钟，在下一队列轮次接续。其它错误、超过自动次数和 needs_attention 留待检查。重试复用原 run、permit 和每日任务名额，新宿主调用另计。按分钟边界判断间隔，避免几秒唤起抖动漏掉整轮。

强杀中断最多自动恢复 2 次，与模型临时错误分别计数。恢复前按 PID、创建时间和执行文件核对并清理该尝试遗留的宿主，无法确认时停下检查。已接受阅读包不重读，暂停期间晚包不能推进检查点。原文、修改依据、原消息及结果历史保全。

“核实论据”“寻找原版”不能只凭视频自述算完成。宿主须明确 task_satisfied；不足时登记草稿、覆盖范围和缺口，run 为 needs_attention，任务仍 pending，不重复自动领取。全文核验状态另记。
