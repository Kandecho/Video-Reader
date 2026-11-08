# Video Reader 文档

第一次使用，从 [安装、接入助手到读取第一条视频](getting-started.md) 开始。

## 使用

| 需要 | 文档 |
|---|---|
| 安装依赖、配置模型、平台登录、调整目录 | [安装与配置](installation.md) |
| 查命令或工具参数、跟进长任务 | [CLI 与 MCP 参考](reader-reference.md) |
| 在 DSH 中安装 Reader + Scroll 整包薄适配 | [DSH 接入](dsh.md) |
| 添加 DSH 索引源、了解社区收录与 Agent 发现 | [发现与收录](discovery.md) |
| 使用 MCPB 接入、查询官方 MCP 服务目录 | [MCP Registry](mcp-registry.md) |
| 区分真实可用、试用中和尚未接入 | [能力状态](capabilities.md) |
| 对比 dsh-bili-scroll 等相关项目 | [相关项目](related-projects.md) |
| 了解分页、续读、原文与校对、材料导出 | [材料与续读](material-delivery.md) |
| 作品列表、分镜预览和批量预览 | [列表与预览](material-reference.md) |
| 管理队列、附言、任务结果及历史 | [队列与历史](tasks.md) |
| 了解版本支持范围和已知限制 | [发布说明](../RELEASE_NOTES.md) |

## 可选的个人工作流

[Scroll](scroll-reference.md) 提供个人推荐、偏好、收件和授权投递。普通读片不需要初始化这些功能。

- [私信 Inbox](inbox-queue.md)：同步授权来信并保留原消息。
- [后台收件与阅读](background-consumption.md)：明确启用后定时检查，在资源允许时处理任务。
- [粗读分流](triage.md)：提出处理建议，保留待定和等待用户的任务。
- [显式批读](scroll-batch.md)：在会话中逐项读取队列。

## 开发与维护

报告问题、复现案例及参与开发，见 [CONTRIBUTING](../CONTRIBUTING.md)。

开发顺序与各阶段验收见[六阶段路线](../planning/roadmap-20261021-source.md)或[阅读版](../planning/roadmap-20261021.html)。维护者从[交接](handoff.md)接续，按需查[架构](architecture.md)、[知识路由](registry.md)和[有效决定](decisions.md)。带日期的研究和验收只用于回查当时事实。

[DSH 薄包验证](https://github.com/Kandecho/Video-Reader/blob/main/validation/dsh-bundle-20261104/report-source.md)记录整包安装；[发现路径实测](https://github.com/Kandecho/Video-Reader/blob/main/validation/dsh-discovery-20261104/report-source.md)记录索引搜索、Git 安装及本机配置。作者索引已公开，开放插件市场和 Awesome DSH 均已收录，官方 MCP Registry 已登记。[社区回查](../validation/dsh-community-20261105/report-source.md)记录最新核对，安装入口见[发现指南](discovery.md)和[MCP 指南](mcp-registry.md)。安装与发现按需维护，不另占开发主线。

返回 [项目首页](../README.md)。
