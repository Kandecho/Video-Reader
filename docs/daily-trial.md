# 首页首条日常试用：运行与依赖

身份：Scroll 本机日试用的规则、依赖和维护入口；末节是注明日期的运行快照，实时状态从 status / 日记录查询。

## 已启用的规则

- 每天北京时间 **20:00**，首次为 **2026-10-23 20:00**。
- 来源是组件登录小号的首页推荐接口；按平台返回顺序，取首个有效普通视频，排除广告项和非视频项。不是主号推荐流，也不保证与手机或浏览器某次刷新逐条相同。
- 不按本地兴趣、模型打分或已读历史换掉第一条。模型仍如实判断，必要时使用既有阅读链；不推荐也照样作为“首页首条试用”投递。
- 同一天固定这一个候选并去重；跨天若平台首条仍相同，允许再次投递，不自行改为第二条。失败或结果不确定不连发、不自动重试。
- 每日只向主号 UID `RECIPIENT_UID` 发一条短私信，并本地留档；不新开聊天，不监听私信、不评论收藏，也不主动上报播放。平台仍会记录正常接口请求。

只改变选片策略。通用阅读、可选深读、显式偏好、反馈记忆和原有普通选片入口保留。个人判断、已预览和完整读过仍分开。

## 两个组件，不是一个绑死的 MCP

| 组件 | 职责 | MCP |
|---|---|---|
| Video Reader | 通用搜索、热门、轻预览、读取、转写、校对、复听及组件登录 | `video-reader`，16 个工具 |
| Scroll Agent | 消费 Reader 的个人工作流：账号流策略、记忆、日记录、投递和触发 | `scroll-agent`，`scroll_round` / `scroll_memory` / `scroll_batch` |

“帮我挑两条视频”是通用自然语言请求，不需要固定品牌口令。普通主题选片可直接用 Reader；个人首页、偏好与日常投递由 Scroll Agent 编排，Reader 是其默认组件。

源码中的 `scroll_agent/` 单向依赖 `video_reader/`。Reader MCP、预览及 transport 不导入 Scroll Agent，不创建其 SQLite；读取组件的 transport 默认只读，只有 Scroll Agent 显式允许私信端点。两个 MCP 都使用同一 `.venv`、配置、模型、凭据及材料，不把自身作为远程 MCP 再绕调用一层。

当前薄插件 0.5.1 将两个独立 MCP 与两个明确分工的 Skill 组合安装，每端 5 个小文件。可单独使用 Reader，不要求启用个人工作流。旧 `video_agent` / `video_memory` 已从 Reader MCP 移除，改由 Scroll MCP 提供；旧 `run.ps1 agent ...` 仅保留惰性 CLI 兼容桥，日常入口为 `scroll.ps1`。

## 外部依赖与运行条件

| 依赖 | 用途及边界 |
|---|---|
| Windows Task Scheduler | 任务 `ScrollAgent-HomepageFirst-RECIPIENT_UID`；本机调度，不依赖 Codex 窗口常开 |
| PowerShell 7 | 任务使用已解析的 `pwsh.exe` 绝对路径；`-NoProfile -NonInteractive -WindowStyle Hidden` |
| 当前 Windows 用户 | Interactive、Limited；不保存 Windows 密码，不使用管理员或系统账户 |
| 电脑状态 | 需要开机、未休眠、该 Windows 用户已登录；锁屏可运行，注销/关机/休眠时错过则不补跑，不主动唤醒电脑 |
| 公共 Python 与本项目 `.venv` | 共用原运行环境，没有新建第二套；不迁移或复制模型及登录 |
| 公共 FFmpeg / ffprobe / Node | 保持任务用户 PATH 可见；已在实际任务进程中解析通过，供既有读取/下载链使用 |
| Codex CLI 与已有登录 | 临时宿主判断使用现有 CLI、用户模型和登录，不要求新 API key；`agent.host.executable=null` 自动定位 PATH 或 Windows 桌面应用的现有 CLI |
| 网络 | 取数/私信需要 B 站；宿主判断需要已有 Codex 服务。本地 ASR 不等于整个 Agent 完全离线 |
| 现有媒体/语音模型 | 仅必要深读时使用原 Reader 资产，不增加推荐模型、数据库服务或云端回退 |

自动定位每次启动重新解析：优先 PATH，未找到时在当前用户 `AppData/Local/OpenAI/Codex/bin/*/codex.exe` 中取修改时间最新的文件，不固化版本目录、不复制程序。也可设置明确路径；明确路径失效会报错，不擅自换宿主。实际选中路径写入每轮 `host/host.log`。执行器当前使用 Codex 的实验性技能隔离开关，CLI 升级后应复核。核心或公共依赖移动后也需检查绝对路径。

任务不并发、不排队补跑，最长 30 分钟，没有自动失败重启。安装脚本要求本机处于 UTC+08 时区；若改变系统时区或日推时间，须同步重建任务。生产可选区间 `agent.wake` 仍关闭，未叠加第二个触发器。

## 入口、状态与反馈

- 安装/更新时间：`tools/install_scroll_task.ps1`，从 `agent.daily` 读取时间和启用状态。
- 任务入口：`tools/run_scroll_daily.ps1` → `launch_scroll.py daily --deliver --scheduled`。
- 手动普通选片：`scroll.ps1 run`，默认仅留档。
- 查状态：`scroll.ps1 status` 或 `scroll_round(action="status")`。包含当天候选、判断、投递结果、最近日记录及任务最后退出码。
- 运行日志：`data/agent/task/YYYY-MM-DD.log` 和 `last.json`；每轮完整记录仍在 `data/agent/rounds/<账号域>/<轮次>/`。
- 暂停：将 `agent.daily.enabled=false`，并可禁用同名 Windows 任务。不会影响通用 Reader。

本机仅 `agent.daily.enabled=true`。普通推荐投递 `agent.delivery.enabled` 和可选区间唤醒 `agent.wake.enabled` 仍为 false；日推授权不泛化成任意推荐自动发送。

反馈直接在当前会话说，例如“昨天那条太长”“今天这个不错”。Agent 从日记录定位对应视频，把你的实际意见记为 feedback；不会把自己的评价或未回复当作你的兴趣。没有私信常驻监听。

材料缓存统一位于 `data/preview/`。原 `data/agent/materials` 是指向它的兼容目录联接，保留旧绝对帧路径，不复制材料。完整媒体仍在 `data/cache/`，登录仍在 `auth/bilibili/`，SQLite 仍沿用 `data/agent/memory.sqlite3`。

## 运行证据快照（2026-10-28）

本次仅只读核对既有任务状态与 SQLite 日运行记录，未触发运行或发送。10 月 24–28 日均为 finished，投递状态为 accepted_not_receipt_verified、receipt_verified=false。10 月 28 日任务日志在 20:00:02 开始，last.json 记录 20:02:21 结束、退出码 0。

这些记录支持业务运行完成、平台已接受发送；尚不支持用户实际收件或长期推荐收益。10 月 23 日人工补发的收件确认仍单独保留。脱敏状态证据见 [日记录快照](../validation/docs-20261028/daily-status.json)。

## 历史运行证据（2026-10-23）

**2026-10-23 首日故障：** Windows 任务确实在 20:00 触发，获取首条 `BV1XBpq6HEHG` 和 5 张预览图后，因配置中的旧 Codex 版本目录已不存在，在宿主评估前失败。20:00:12 退出码 1，业务状态 `failed`、投递 `not_sent`，该次失败运行没有私信发送尝试；不是接口接受但未收件的问题。当次排查中的网络闸门状态不能外推为持续运行状态。

已改为上述自动定位，配置不再固定旧版本路径，针对宿主的 17 项运行测试通过。真实验证主动移除 PATH 中的 Codex，仍找到桌面应用现有 CLI，并用今天的 5 张缓存图完成模型判断；该隔离验证为 0 次 B 站请求、0 私信，生产文件哈希不变。修复验证与排查证据见 `validation/daily-incident-20261023/`。

**用户随后明确授权补发，22:11 已单次发送原视频，并已确认收到。** 消息键 `7699865811817091324`；原轮次完成，当前为 `receipt_confirmed_by_user` / `receipt_verified=true`，原始接口接受结果仍保留。复用了缓存评估；视频长 360 秒，超过原深读上限 300 秒，仍诚实标记材料不足，不换第二条。仅 1 次私信 POST，没有重新获取首页、下载或再次评估。原失败另存 `recovery-before.json`，实际发送见 `recovery-result.json`，收件确认见 `receipt-confirmation.json`。原定时任务的退出码 1 保留为 20:00 初次运行历史，不代表补发失败。没有重置发送账本或修改调度；截至该次记录，自然定时发送及其收件尚未完成验收，后续按当前日记录判断。

用户明确请求查看主号回复后，仅做 1 次 GET，读取到消息 `7699866735390045365`，没有额外回复或启动监听。用户评价“我认为这条可以”，原文已作为 feedback 关联视频留档。后续偏好方向是用户二值反馈结合 Agent 自动标签与探索，不预设内容价值；详见 `docs/decisions.md` 对应 2026-10-23 条目。本次只记入现有记忆，未新增搜索任务或改变每日首条策略。

以下为 2026-10-23 凌晨注册时的验收快照，实时状态以 Scroll status 和 Windows 任务为准。

161 项回归通过，两个 Skill 校验及 Codex 双 MCP 实测通过；Claude 同版包格式校验通过，未安装。隔离真实“首条”判断完成、同日复用通过，未发送私信，也未占用生产日记录。

Windows 任务已真实提前启动：依赖解析与 Python 启动成功，返回 `before_daily_time`、退出码 0，证明此时不取候选或发信。在该次提前检查时首个 20:00 运行尚未发生；它只证明时段约束，不是收件验收。

注册与组件拆分证据见 [0.8.0 验收](../validation/scroll-0.8.0/report-source.md)，故障与人工恢复见 [首日排查](../validation/daily-incident-20261023/report-source.md)及同目录恢复记录。当时预算尚未覆盖深读内部请求；rc1 已统一原生请求与 yt-dlp urlopen 的账号预算，底层重定向不逐跳计数。当前材料与理解边界见 Scroll 操作参考。
