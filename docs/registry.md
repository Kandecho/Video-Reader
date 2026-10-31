# 项目知识路由

身份：只定位主维护处和读取条件，更新于 2026-10-29。当前事实与历史证据分开读取；历史报告不自动生成新任务。

## 当前任务入口

| 知识 | 主维护位置 | 何时读取 |
|---|---|---|
| 目的与直接使用 | [README](../README.md) | 理解 Reader 服务什么、怎样调用 |
| 有效决定与未决事项 | [decisions](decisions.md) | 查响应速度、初校职责、既有边界及本次授权 |
| 当前能力、缺口与后续方向 | [路线源稿](../planning/roadmap-20261021-source.md) B–F；[阅读版](../planning/roadmap-20261021.html) | 讨论机制或接续开发；区分事实、目标与候选验证 |
| 当前接续 | [handoff](handoff.md) | 下一次任务先读；定位已完成阅读及尚未同步的宿主流程 |

## 操作与运行

| 知识 | 位置 | 何时读取 |
|---|---|---|
| Reader 操作 | [reader-reference](reader-reference.md)、[阅读 Skill](../skill/SKILL.md) | 查工具及校对提交方式；注意参考开头的目标与当前指令差距 |
| 安装与发布候选 | [installation](installation.md)、[候选记录](../validation/docs-20261028/summary.json) | 查公共依赖、路径、可选模型和已测候选范围 |
| 材料、游标和导出 | [material-delivery](material-delivery.md) | 修改/接续分页、来源、修订或完整交付 |
| 列表与分镜预览 | [material-reference](material-reference.md) | 查 UID/作品分页、轻量/密集与批量预览 |
| Scroll 普通工作流与批量 | [scroll-reference](scroll-reference.md)、[scroll-batch](scroll-batch.md)、[Scroll Skill](../scroll-skill/SKILL.md) | 个人选片、记忆、显式多片队列；不将推荐流程塞回 Reader |
| 首页首条日试用 | [daily-trial](daily-trial.md) | 查既有 20:00 Windows 任务、依赖及运行快照；实时状态另查 status |
| YouTube Cookie | [handoff 的凭据接续](handoff.md#youtube-cookie-接续2026-10-28)、[平台参考](reader-reference.md#平台配置与云端选项) | 查私有位置、失效替换及长期维持缺口，不把历史检查当当前登录证明 |
| 双宿主薄插件 | [插件参考](reader-reference.md#codex--claude-code-薄插件-053) | 查共享核心、生成与安装；当前宿主指令尚未按新体验调整 |
| 许可与第三方来源 | [LICENSE_REVIEW](../LICENSE_REVIEW.md)、[THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md) | 改依赖、整理源码候选或准备公开 |

## 证据与历史

| 知识 | 位置 | 何时读取 |
|---|---|---|
| 已完成阅读及可继续材料 | [真实任务报告](../validation/task-reading-20261028/report-source.md)、[接续材料](../validation/task-reading-20261028/resume-check.md) | 人工复核、复用已读材料或设计现有错例对照 |
| 当前功能基线 | [rc2 验收](../validation/reader-0.10.0rc2/report-source.md)、[rc1 整轮](../validation/reader-0.10.0rc1/report-source.md) | 核实修复、功能和宿主/安装证据范围 |
| 本次文档维护 | [docs-20261029](../validation/docs-20261029/summary.json) | 查归档、同步、核对范围与保全记录 |
| 其他研究、版本及旧决定 | [history-index](history-index.md) | 按问题回查；日常接续无需通读历史 |
