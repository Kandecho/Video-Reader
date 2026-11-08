# Video Reader 接续

身份：2026-11-06 阶段 6 后台试跑接续。先读本页，再按[registry](registry.md)定位；当前待办只在[路线](../planning/roadmap-20261021-source.md)主维护，历史报告不自动授权下一轮工作。

## 当前状态

2026-11-08 冻结架构审计后的 fix 批次已完成。冻结归档保存修改前 162 个源码／测试／文档与证据文件，不含凭据、模型或私有材料。修复统一联网管控并保留原访问模式、收口认证和平台协议、音频续点、派生缓存代际与历史轨回查、作业配置一致性、图像重复交付、任务／调度／记忆／宿主边界及构建／测试隔离。整合 448 项及单独真实 MCP 2 项通过，共 450 项；Skill／适配器更新后相关 19 项复验通过，独立代码复核无实质发现。此前两项 stdio 协议待验证已在支持进程握手的权限环境通过，不据此宣称历史原子替换问题已修。源 Skill 与本地 Codex/Claude 适配器 0.5.6 已同步，既有 MCP 连接需重启加载新参数。源码按主题分批提交、暂不发布，未更改模型／配置／后台收件／发送许可；feature 方向和非阻塞未知继续保留。见[本批结果](../validation/architecture-fixes-20261108/README.md)与[当前路线](../planning/roadmap-20261021-source.md#e-冻结架构基线修复)。

2026-11-07 空 CLI 闪现已复现为本组件队列计划任务启动：20:46:52 捕获 Windows Terminal 可见约 1 秒，原 pwsh -WindowStyle Hidden 未能避免。新增共用无窗口入口：同一 Python 安装的真实 GUI pythonw.exe → CREATE_NO_WINDOW → 原 PowerShell runner。本机 .venv/pythonw.exe 实为控制台 shim，已通过 PE 子系统检查避开。三个现有任务仅更新 Action，收信仍 Disabled，Queue 仍 5 分钟，日推仍 20:00；未为验证触发日推或收信。启动器 3 项与后台 30 项检查通过；手动及 20:55 自然触发均退出 0，窗口事件为 0。证据见[诊断结论](../validation/console-flash-20261107/report-source.md)。

2026-11-07 用户要求先关闭后台巡检收信：sync_enabled=false，Windows `Video Reader Inbox Intake` 已禁用；`Video Reader Task Queue` 保持 Ready、5 分钟间隔，enabled/read_enabled 仍为 true。手动给链接/BV读取或明确要求单次同步 Inbox 不受此后台开关影响；只向小号转发不会再定时检测入队。收件的 60 分钟参数保留，未经用户再次要求不恢复后台收信。已核对当前待办 0，状态证据在 data/stage6-validation-20261106/intake-disabled-20261107/verified-state.json。

用户本轮澄清“清队列”是完成任务，不是把未完成项归档。代理误归档的三条已恢复，由当前会话实际阅读、核查后登记 done：论据核查、EmbodiedNPC 环境感知源码对照、Charlotte Fraza 原版定位。产物与观察/完成记录在 data/reading-results/20261106/host-completion。当前待办 0、总 done 14，全文核验未冒称完成，后台失败历史保留。

后台模型通路另已定位并修复：Windows 系统代理未传给独立 Codex CLI。相同最小请求原环境 45.766 秒超时，显式传既有代理后 7.328 秒成功；共享 host_runtime 增加仅对子进程的代理继承后，原模型实际读图及 schema 返回在 18.157 秒通过。显式代理（包括空值）优先，NO_PROXY 保留，不改系统或父进程。代理新检查 5 项及原宿主 17 项通过，独立代码复核通过。[诊断结论](../validation/host-route-20261106/report-source.md)。不据单次成功宣称长期调度稳定，未重跑已完成队列。

用户最新要求入队检测改 60 分钟，与队列重试分开；模型连接超时应短间隔重试。当前 intake_interval_minutes=60、queue_interval_minutes=5、max_host_retries=2，时段仍北京时间 09:00–23:00，每天最多启动 3 条、同时 1 条。额度不足只暂停阅读，脚本收件可继续。Windows 任务改为 `Video Reader Inbox Intake` / `Video Reader Task Queue`，统一从后台配置生成，旧合并触发器已移除。后台真实任务曾超时并按短间隔重试，后续仍出现 workspace routing discovery failed；本轮内容由当前会话补完；宿主通路后续按上段代理对照单独修复。实时状态用 background-status。已有 20:00 日推未改。[后台操作](background-consumption.md)、[阶段 6 结论](../validation/stage6-background-20261106/report-source.md)。

检查是纯脚本；允许阅读才使用现有宿主。Controls 在通用任务域持久保存许可、上限、暂停与尝试数；Scroll 负责 Inbox/定时触发，复用 Consumer/Reader，未另造阅读核心。供应商余额未知，本地上限不是余额。CPU/内存、Reader 活动 job 与手动 hold/pause 可让路，无法识别整个桌面或所有 Codex 聊天的忙闲。

三条独立附言已按本轮用户确认写为 request 并关联原消息：q_40a8868acc054405bd3d13550c9b6484 核论据；q_1110c859adac4e8f955471b43651f1b6 看环境感知；q_dbe89b8399d447cea4da894e9479bc05 找原版。各保留两条原消息。这不是以后自动邻接配对的授权，也不是用户广泛兴趣。

新增 task_satisfied 判定；外部事实核查/原版查找未满足时登记草稿、run needs_attention、任务 pending，不重复领取。额度错误锁定 model_quota 后需明确恢复原 run/许可。host_timeout / host_transport 按队列短间隔最多自动重试 2 次，不新占任务名额；其它错误停留待检查。显式 retry 不受自动次数限制，仍遵守宿主调用预算，不同步 Inbox、不重置自动次数。暂停后恢复之间的晚包不得推进检查点。

## 本批验证及剩余

晚间间隔拆分与短重试的定向检查为后台 30 项、单条消费 12 项、插件 7 项通过；双 Windows 任务已核对为 PT1H / PT5M，原合并任务不存在。首次真实重试沿用原 run，今日任务数仍 1，宿主尝试 1→2，未执行入队检测。证据在 data/stage6-validation-20261106/interval-split，连接能否恢复另看实时状态。

全量 399 项通过；后续暂停竞态修复又通过后台 21 项与单条消费 12 项。真实强杀 worker 后旧宿主仍存活，恢复先按进程身份清理旧宿主，再接回同一 run：已接受块 4→6、不重读首包、结果恰好 1 条。此实验使用受控宿主响应，未测试新一轮真实模型语义质量；阶段 4 真实宿主颜色/字幕冲突任务证据仍在。Windows 计划任务父脚本退出后，采用相同启动方式的 20 秒测试子进程继续完成；测试任务已删除。

阶段 6A/6B 的本地功能、真实恢复及脚本调度验证完成；真实视频连续消费与推荐收益继续试跑。推荐记录核对为 1 条明确正反馈、1 条探索偏好、15 条 Agent 观察；已加强不预设学习/效率/商业价值、不从单例或未回复扩大偏好的宿主规则，尚不能宣称推荐更准。6C 需按真实反馈对照收益，日试用仍固定首页首条，不改选片。

本地 Reader 21 / Scroll 8 工具；已发布资产仍为 20 / 7。CLI 使用当前源码，已有 MCP 连接需重启加载 scroll_background；没有发布、提交或推送本批变更。阶段 5 历史 WinError 5 原因未定，本批全量通过不代表它已修复。

## 已完成成果与回查

阶段 1–5 的具体状态移至[上次完整交接](history/handoff-through-stage5-20261106.md)，本页不重复旧进展。阶段 3/4 内容目录、queue-search、单条宿主消费已可用；阶段 5 保留按疑点看图/复听/局部修改，不加独立初校模型。

两篇笔记已保存到用户指定的私人笔记库，原产物保留在本地阅读结果中。笔记与验证结论、逐项改进日志分开。TAS 只作用户指定的项目参考，未修改该项目。

历史检索先 queue-search→queue-show→登记笔记/来源→content 原段与源图，不默认重转写，不存在全局历史语义库。既有材料、校对与原消息继续保全；任务库不随平台登录变换，材料仍有账号绑定。

默认本地、Gemini 关闭、失败不转云；不读取 watch/BiliNote/旧原型凭据。发布、接入、日推及旧样本按 registry 路由，不为接续重做已完成任务。授权不包含发送新回执、修改 TAS 或发布本轮变更。

## YouTube Cookie 接续（2026-10-28）

继续用户手动导出的短期 Cookie，失效后重导，不启用自动登录服务、不展示凭据。私有位置见[旧交接](history/handoff-through-20261031.md#youtube-cookie-接续2026-10-28)，历史成功不代表当前有效。[平台参考](reader-reference.md#平台配置与云端选项)。
