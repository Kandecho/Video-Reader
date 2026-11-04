# 任务职责拆分与架构修复

2026-11-04。先完成用户指定的六项队列产物，再修复此前架构检查的中高项，并按证据处理低项。工作区保留此前多批未提交修改，本批没有提交、推送或发布。

## 最终行为

实现独立 reading_tasks 模块与 tasks.ps1、Reader video_tasks。Scroll 的 queue/triage/batch 入口兼容；Inbox 拥有原消息、同步及其事件。通用任务保存来源快照、意图、结果和事件，库身份不随登录变化；查询无需 B 站登录或初始化个人 Memory/FTS。

沿用现有 SQLite 文件和旧库键，不搬动或重写原消息。Store 提供公共连接，Inbox 通过公开的事务内任务接口保持消息/入队/游标原子提交。legacy 适配器导入旧来源和分流意图；材料账号绑定保留。来源账号与任务库分离后，消息历史游标增加来源账号绑定，跨账号复用拒绝；旧游标需重查时明确失效。

scroll_report 已联通是否入队、原初分流、当前任务状态及结果引用，提供 preview 与显式 send。轮次和汇报共用发送通道及 accepted/uncertain 幂等账本。实际只生成预览，真实发送为 0；所有发送验证使用假平台。

## 原九项检查的处理

| 原问题 | 处理与证据 |
|---|---|
| 短链绕过 offline/预算 | sources.resolve 不联网；Platform 把跳转响应作为受控材料缓存，验证目标而不盲跟随；覆盖离线 miss/cache、预算、暂停与恶意目标 |
| 默认深检查/长材料锁 | 默认 read/文字阅读不计算新 OCR，复用缓存且保留未核验标识；显式参数/evidence 可深入。frame-details 独立锁和记录，不等长会话锁，旧快照保存不覆盖新细节；真实本地视频夹具验证 |
| 收件借投递配置 | agent.inbox.sender_uid 独立，首次优先迁移已保留 Inbox peer，再兼容旧投递值；以后改投递对象不变更收件范围 |
| Inbox/Queue 私有接口及表交叉 | Inbox 拥有消息/同步表；公开入队、来源与游标接口；任务不联查 Inbox schema。消息原始修订与任务来源修订分别保全 |
| 私有 manifest 扫描 | Reader.materials/catalog 与 speech_index 提供公开查找和身份信息；任务模块不扫描 manifest 或调用 _speech。状态/汇报跳过无用的材料目录查询 |
| 附言/要求混合 | 保留旧 task，note/annotation 保存 original/comment/request/uncertain；分流提交与意图同事务；任务结果独立于初分流 |
| CLI/MCP/Skill 契约散落 | 通用 task API 和参数共用；reading_policy 同步 MCP、源码 Skill 与生成薄适配器，及时回答不以全片校对为前置条件 |
| Memory 兼任连接层 | Store 独立；Memory 只初始化个人业务，通用队列不需 FTS；共享 SQLite 继续可用 |
| 记录工具预导入 OCR | 保留 Windows MCP 原生库预导入，已有首次在线程导入死锁约束，未证明可安全删除；独立任务 CLI 不经过它，没有另建服务器 |

未重跑同等深度的全片性能基准，不把减少默认工作量表述为同等核查深度加速。Qwen 强制中文和历史 Windows 原子替换问题仍保留原调查，不据本批变化宣称解决。

## 实际接口发现与修复

新进程试验发现 FastMCP 会对可空字符串参数预解析 JSON，导致 item_ids_json 列表变成数组后又违反字符串 schema。依据实际依赖的 func_metadata.pre_parse_json 定位，JSON 字符串参数改成明确的 str 默认空串；同样修正 round 决策与 triage 判断参数。补了框架参数解析回归，并再次用真实 stdio 报告调用通过。没有将工具错误误报为任务或发信失败。

## 验证结果

- 完整 unittest discover：330 项，58.380 秒，OK。
- 最后的账号/库分离、配置升级、JSON 参数解析及相关专项：45 项，4.833 秒，OK。后者包含全量之后增加的回归，未为凑计数重跑全量。
- 新 Reader MCP 20 工具、Scroll MCP 7 工具；通用队列与原附言/结果查询、真实 scroll_report 预览通过。
- 独立 CLI、旧 Reader agent 桥一致；禁用登录和个人 agent 的隔离配置仍查到六项 done。
- 六项原附言、7 条消息关联、旧初分流和产物哈希复核一致；pending=0，真实发送=0。
- 本地 allowlist 源码候选 125 文件，版本读取 pyproject 的 0.10.0rc6；包含 reading_tasks 与新启动器，可用隔离配置执行空队列查询。不含凭据、模型或用户数据；未发布。它不代替跨机安装与第三方宿主验收。
- 源码与生成 Codex/Claude 薄适配器策略一致。当前已运行连接仍需重启以发现新工具；没有直接编辑宿主缓存。

完整日志、实际接口 JSON、结果回查与源码索引保留本地；精选结构化数据见 summary.json。当前操作与职责见[任务参考](../../docs/tasks.md)及[架构](../../docs/architecture.md)。

结果阅读页包含八个面板和一张职责图；已用无界面浏览器检查 1440/390 宽度，未见整页横向溢出或脚本错误，并实际查看桌面、手机与主图截图。原文笔记保留原有措辞，页面关闭风格改写检查。新操作文档和六篇结果的本地链接已核对。
