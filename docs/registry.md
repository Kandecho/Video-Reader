# 项目知识路由

本页供开发和维护时定位当前决定、实现与历史证据。安装和日常使用请从 [文档首页](README.md)或[首次使用](getting-started.md)开始。

身份：只定位主维护处和读取条件，更新于 2026-11-09。当前事实与历史证据分开读取；历史报告不自动生成新任务。

## 当前任务入口

| 知识 | 主维护位置 | 何时读取 |
|---|---|---|
| 目的与直接使用 | [README](../README.md) | 理解 Reader 服务什么、怎样调用 |
| 有效决定与未决事项 | [decisions](decisions.md) | 查响应速度、初校职责、既有边界及本次授权 |
| 当前能力、缺口、阶段顺序与验收 | [路线源稿](../planning/roadmap-20261021-source.md)、[当前待办](../planning/roadmap-20261021-source.md#f-下一阶段与验收)、[阅读版](../planning/roadmap-20261021.html) | 已完成安排移至[阶段 5 后快照](../planning/roadmap-through-stage5-20261106.md)；实施证据见[阶段 1](../validation/stage1-interaction-20261106/report-source.md)、[阶段 2](../validation/stage2-reliability-20261106/report-source.md)、[阶段 3/4](../validation/stage34-content-consumption-20261106/report-source.md)及[阶段 5](../validation/stage5-reading-support-20261106/report-source.md)；具体摩擦持续登记，相关阶段穿插修正；安装与发现贯穿维护 |
| 当前接续 | [handoff](handoff.md) | 下一次先读；定位当前阶段及可复用样本，旧批次日志从历史索引回查 |
| 整体架构与边界检查 | [当前架构](architecture.md)及[修复前检查](architecture-20261104.md) | Reader/通用任务/Scroll 的当前职责、状态与存储，以及修复和保留项 |
| 高内聚低耦合与能力替换审计 | [完整审计及综合结论](../validation/architecture-audit-20261108/README.md) | 2026-11-08 合并首轮证据与一次补查，覆盖平台获取、媒体处理、任务、推荐、记忆及投递的变化范围；源码链接固定至修复前提交 |
| 冻结基线后的架构问题修复 | [修复记录](../validation/architecture-fixes-20261108/README.md)、[验证与基线摘要](../validation/architecture-fixes-20261108/summary.json) | 2026-11-08 fix 批次与 450 项验证；原审计／本地源码归档不改写，feature 与非阻塞项保留；源码分批提交，暂不发布 |
| 面向使用者的文档 | [文档首页](README.md)、[首次使用](getting-started.md) | 清楚区分人类使用步骤、参数参考和开发维护入口 |
| DSH 接入与 Agent 发现 | [整包薄适配](dsh.md)、[薄包验证](../validation/dsh-bundle-20261104/report-source.md)、[收录确认](../validation/dsh-community-20261105/report-source.md)、[呈现与检索](../research/dsh-presentation-20261104/report-source.md) | 开放插件市场已收录 0.1.0，Awesome PR 已合并并核对目录源；npm 未发布 |
| 对外能力状态与相关实现 | [能力状态](capabilities.md)、[相关项目](related-projects.md) | 真实可用、试用与未完成分别说明；独立 B 站账号和授权私信已用，不作整体稳定性或竞品排名承诺 |
| 长视频内容检索与实时陪看对照 | [Sense Now / See Now](../research/sense-now-comparison-20261104/report-source.md) | 固定源码比较分块检索、实时输入和任务工作流；未安装第三方项目，不据合成 benchmark 排性能 |
| 分层提速与视觉证据上下文 | [MoonDigest 对照与上下文调查](../research/moondigest-context-20261108/report-source.md) | 2026-11-08 固定上游源码、区分 MCP 主聊天与独立宿主，回查重复交付复现及待测指标；后续方向只在路线维护，未启动实现 |
| 回答级溯源与按需补看 | [帧寻对照](../research/zhenxun-comparison-20261108/report-source.md) | 2026-11-08 找到作者公开源码；看引用校验的实际边界、局部补看、浏览器截图隔离与视频图像重发，区分演示时间和被分析原片时间 |
| DSH 索引与社区收录 | [发现指南](discovery.md)、[作者索引](../discovery/dsh/README.md)、[实测](../validation/dsh-discovery-20261104/report-source.md) | 本机搜索→固定 Git 安装→调用已通；作者索引、社区目录和通用 MCP Registry 不混为一谈 |
| 官方 MCP Registry 与 MCPB | [接入和查询](mcp-registry.md)、[登记验收](../validation/mcp-registry-20261104/report-source.md) | 两服务 0.1.0 已登记且公开回查通过；同一 Release 提供完整源码和两个薄包，仍需预装 Windows 核心 |

## 操作与运行

[通用任务、结果与汇报](tasks.md)是当前队列主入口；实现归 reading_tasks，Scroll 仅保留兼容适配及个人收发。

| 知识 | 位置 | 何时读取 |
|---|---|---|
| 内容目录与历史材料回查 | [content-index](content-index.md) | queue-search→原笔记/来源→时间块/词法候选→原段与源图；查修订与像素绑定、分页及未命中补看 |
| Reader 操作 | [reader-reference](reader-reference.md)、[阅读 Skill](../skill/SKILL.md) | 查工具、按疑点深入与校对提交；已同步及时回答，不把全片逐段校对作为每次答复前置 |
| 安装与当前发布 | [installation](installation.md)、[本批验收](../validation/release-20261104/report-source.md) | 查 MIT、公共依赖、干净安装、代表任务与本版发布事实；旧候选记录保留历史范围 |
| 材料、游标和导出 | [material-delivery](material-delivery.md) | 修改/接续分页、来源、修订或完整交付 |
| 列表与分镜预览 | [material-reference](material-reference.md) | 查 UID/作品分页、轻量/密集与批量预览 |
| Scroll 普通工作流与批量 | [scroll-reference](scroll-reference.md)、[scroll-batch](scroll-batch.md)、[Scroll Skill](../scroll-skill/SKILL.md) | 个人选片、记忆、显式多片队列；不将推荐流程塞回 Reader |
| Scroll 单轮状态与恢复 | [操作参考](scroll-reference.md#单轮状态与显式恢复2026-11-04)、[11 月 4 日验收](../validation/scroll-state-20261104/report-source.md) | 指定轮次的阶段、执行者、错误链、事件与显式留档接续；查询不触发重试，恢复不发送 |
| Scroll Inbox、队列与历史 | [操作参考](inbox-queue.md)、[本批验收](../validation/inbox-queue-20261104/report-source.md)、[通用任务](tasks.md) | 显式同步授权来信、旧消息只留历史、新视频入队与原消息追溯；后台试跑由单独授权控制，见 background-consumption |
| Scroll 粗读建议分流 | [操作参考](triage.md)、[试跑验证](../validation/triage-architecture-20261104/report-source.md) | 显式 prepare/material/content/submit，类型、附言意图、建议/待定/等待用户；不执行方案或启动后台消费者 |
| 后台收件与消费 | [操作与参数](background-consumption.md)、[阶段 6 验证](../validation/stage6-background-20261106/report-source.md) | 查 09–23 点、独立入队 60 分钟 / 队列与临时重试 5 分钟、每日 3 条、资源等待与检查点；不与 20:00 日推混用 |
| 首页首条日试用 | [daily-trial](daily-trial.md) | 查既有 20:00 Windows 任务、依赖及运行快照；实时状态另查 status |
| YouTube Cookie | [handoff 的凭据接续](handoff.md#youtube-cookie-接续2026-10-28)、[平台参考](reader-reference.md#平台配置与云端选项) | 查私有位置、失效替换及长期维持缺口，不把历史检查当当前登录证明 |
| 双宿主薄插件 | [插件参考](reader-reference.md#codex--claude-code-薄插件-055) | 查共享核心、生成与安装；当前 Skill/MCP 已同步及时回答与按疑点深入 |
| 许可与第三方来源 | [LICENSE_REVIEW](../LICENSE_REVIEW.md)、[THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md) | 改依赖、整理源码候选或准备公开 |

本轮诊断修复： [rc6 实施与真实复验](../validation/diagnosis-repairs-20261031/report-source.md)。

## 证据与历史

| 知识 | 位置 | 何时读取 |
|---|---|---|
| 已完成阅读及可继续材料 | [真实任务报告](../validation/task-reading-20261028/report-source.md)、[接续材料](../validation/task-reading-20261028/resume-check.md) | 人工复核、复用已读材料或设计现有错例对照 |
| 当前功能基线 | [rc6 修复](../validation/diagnosis-repairs-20261031/report-source.md)、[rc2 验收](../validation/reader-0.10.0rc2/report-source.md)、[rc1 整轮](../validation/reader-0.10.0rc1/report-source.md) | 核实修复、功能和宿主/安装证据范围 |
| 11 月 3 日文档维护 | [docs-20261103](../validation/docs-20261103/summary.json) | 回查当时归档、同步与保全；最新路线与旧快照的分界见历史索引 |
| 11 月 3 日阅读与选图观察 | [双片阅读](../validation/reading-pair-20261103/report-source.md)、[攻略选图](../validation/guide-image-selection-20261103/report-source.md) | 复用已读材料，核对锁等待及选图边界 |
| 其他研究、版本及旧决定 | [history-index](history-index.md) | 按问题回查；日常接续无需通读历史 |
