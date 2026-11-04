# Scroll 单轮状态与恢复

日期：2026-11-04。范围为用户选择的“先做 Scroll 状态与恢复”。核心版本仍为 0.10.0rc6；未发布新版本。Inbox、后台持续阅读、资源调度和 Reader 默认核查策略未纳入本批。

## 结论

现有单轮工作流已增加阶段、执行者、心跳/真实进展、等待原因、错误链、材料及宿主评估检查点、产物定位和持久历史事件。CLI 与 MCP 使用同一 SQLite 状态。显式 recover 复用原轮次材料与有效判断，始终只留档；无候选证据时拒绝原地恢复。

73 项相关测试通过，涵盖原 Agent/宿主、每日首条、批量队列及新增 16 项状态恢复场景。真实 CLI 和新 MCP 进程对两个历史轮次的只读查询通过。业务 runs、deliveries、配置、日索引、任务快照及原轮次文件在前后指纹比较中一致；只新增兼容的事件表/索引和查询锁文件。未恢复生产任务、获取新候选、调用模型、补发、同步私信或调整调度。

## 历史原因核对

| 轮次 | 已核实事实 | 当前查询和恢复含义 |
|---|---|---|
| 2026-11-03 | task 日志止于笼统 ReaderError；host.log 有模型列表刷新超时、路由发现重连、WebSocket 回退 HTTPS，最终 turn.failed 为 workspace routing discovery timed out。保存了 1 条候选和 1 条预览，投递 not_sent | 状态 failed；错误链显示 host_transport 与具体宿主错误，可显式复用保存材料。这里只定位到宿主路由发现阶段超时，未进一步判断本地网络或服务端原因，也未修复外部传输 |
| 2026-11-01 | SQLite 仅有 preparing 初始快照，候选和预览均为 0，无 packet/result/host 日志。只读执行者核对与空闲 round 锁表明没有执行者继续持有该轮次；既有 Windows 任务 Ready，上次退出码 1 | 查询投影为 interrupted，recorded_status 仍为 preparing，历史阶段标明未记录。无候选/预览时 recover 不重新取首页、不替换旧轮次。该历史任务本批未重跑 |

当前宿主存在多组正常 MCP 服务进程，不能只按 Python 进程存在与否判定旧日推仍在执行。本批仅核对进程与定时任务；未停止既有 MCP 或日推。

## 实现

- `scroll_agent/runtime.py`：每次执行持有轮次所有权锁；心跳与真实进展时间分开。状态通过短时观察锁序列化查询，不等待单轮执行锁或媒体锁。失去所有权的 running 投影为 interrupted，查询不改写原业务快照。旧轮次没有阶段证据时保留未知，不补造进度。
- `scroll_agent/memory.py`：runtime 字段与业务结果在短 SQLite 事务内合并，旧快照写回不覆盖新的心跳/阶段。run_events 保留状态、进展、错误及显式恢复记录；按账号隔离。查询默认交付最近 100 条事件，完整事件仍在数据库中。
- `scroll_agent/agent.py`：日轮先登记再开始发现；候选、每条预览、宿主判断及增强材料保存检查点。恢复原 run_id，复用已有材料和判断；只有缺失的原候选材料需要补齐。现有同步 Reader 深读关联 session，只有实际返回 job 时才登记其 ID。选片评估仍明确不等于完整阅读。
- `scroll_agent/host.py`：保留有界日志尾部的错误事件、退出码、超时和因果信息；后续调用前保存旧宿主日志/决策/schema，避免覆盖原证据。回调记录宿主 PID 和等待宿主响应。异常退出时只清理本次创建的宿主进程。
- 发送先保留 sending 快照；中断后依据账本显示 uncertain、平台接受或拒绝，不倒退到 not_sent。recover 本身没有发送路径，CLI 拒绝 --deliver，MCP 拒绝 dry_run=false。原平台接受、用户确认与结果不确定的边界保留。
- CLI `status ROUND_ID` / `recover ROUND_ID`、Reader 的旧 agent CLI 兼容桥和现有 scroll_round 工具均接入。没有增加 MCP 工具或第二套读取核心。

## 验证

最终相关回归命令：

```powershell
$env:TEMP = 'D:\IA\apps\video-reader\.test-work\tmp'
$env:TMP = $env:TEMP
$env:PYTHONPATH = 'D:\IA\apps\video-reader\tests'
& '.venv/Scripts/python.exe' -m unittest test_agent test_agent_runtime test_scroll_daily test_scroll_batch test_scroll_runtime
```

结果：73 tests，27.045s，OK。新增 16 项包含真实子进程持锁后 os._exit 突然退出、查询不被执行锁阻塞、原候选恢复、日轮中断去重、宿主因果链与历史保全、复用已完成评估、旧 preparing 投影、旧宿主日志诊断、发送中断防重、账本已接受但结果未写回、账号隔离和 CLI/MCP 的只留档约束。

状态实测脚本为本目录 `verify_status.py`，原始证据为本地 `status-smoke.json`，均不纳入公开源码。CLI 查询两条记录分别为 0.453s / 0.454s（包含进程启动）；新 MCP 初始化后查询分别为 0.031s / 0.031s。两端一致返回 interrupted / failed。前后业务指纹一致，生产发送为 0。

Windows venv python.exe 可以是启动器，实际执行者 PID 与 Popen PID 不同；中断测试通过文件信号让实际子进程 os._exit，避免把终止启动器当作执行者死亡。测试临时目录放在工作区，以避开沙箱临时目录权限差异。

最初的真实 stdio 验证在受限沙箱中启动未返回；只停止本次创建的两个验证进程后，经实际宿主通路复测通过。该启动等待不计入上述查询耗时，不声称已解决历史宿主接入通路问题。

## 使用与限制

操作见[Scroll 参考](../../docs/scroll-reference.md#单轮状态与显式恢复2026-11-04)。CLI 直接读取当前安装源码；已经启动的 MCP 进程需要重启连接后加载新代码，实测使用新进程，没有重启用户已有服务。

本批没有给旧 preparing 补造丢失的候选，没有触发自然 20:00 日推来验收，也没有验证真实生产恢复或收件。恢复成功和模型服务恢复、材料准备完成和宿主完整读完是不同判断。Inbox、后台队列与额度策略继续按路线 F.4 讨论，不能据本批完成自动进入下一阶段。
