# MCPB 与官方 Registry 验收

日期：2026-11-04。范围为整包项目的两个 MCP 接入包及官方目录登记；核心仍为 0.10.0rc6，MCPB 版本为 0.1.0。轻量内容目录、storyboard 复用和问题检索仅加入路线，未实施。

## 已完成的准备和本机验证

- 官方 `@anthropic-ai/mcpb` 2.1.2 校验两个 0.3 清单通过；官方 Registry `mcp-publisher` v1.8.7 校验两份 server.json 通过。发布工具 Windows 资产摘要与官方 Release digest 一致。
- 每个包仅含四个文件：manifest、共享启动器、说明与 MIT LICENSE。不含核心副本、Python、模型、账号或运行材料。两服务复用同一现有核心，通过同一项目 Release 发布。
- 三项适配器测试和一项源码分发回归通过：包内容和重复构建一致；两个服务、默认/自选配置与无关工作目录；中文/空格路径；缺失核心明确报错且 stdout 不污染协议。
- 从实际归档解包、按清单替换用户配置并启动 MCP：Reader 20 工具，通用队列、本地合成视频、字幕 offset 0/1 通过；Scroll 7 工具，离线状态查询通过。核心目录为既有中文/空格 junction，包路径也含中文/空格。
- 初始隔离测试禁用了登录管理，Scroll 状态返回 managed_login_disabled；启用但没有账号时返回 login_required。按既有契约改用现有登录离线读取后通过；没有修改业务实现或把匿名状态宣称为已用能力。材料、任务和 Scroll 工作状态位于隔离目录，未复制凭据。
- 官方 Registry 身份认证成功，命名空间为 io.github.Kandecho/*。发布者凭据保存于官方工具私有位置，不进入源码或 Release。

## 分发与目录状态

已公开 [mcpb-v0.1.0 Release](https://github.com/Kandecho/Video-Reader/releases/tag/mcpb-v0.1.0)，来源 c50f0f65a3c3616a849223a35fd872fcb7d1a26a。完整源码 ZIP 的清单含 169 文件；两个 MCPB、源码 ZIP 和摘要文件共四个资产，GitHub 服务端 digest 与实际公开下载均核对一致。源码 ZIP 保留发布前准备快照，最终登记回执以 main 上本文及 summary.json 为准。

北京时间 2026-11-04 23:06:19–20，`io.github.Kandecho/video-reader` 与 `io.github.Kandecho/scroll-agent` 0.1.0 串行发布成功。未经认证的公开 API 按 Kandecho 查询返回两条；精确 latest 查询均为 active、isLatest=true，版本、安装包地址和 SHA-256 与[Reader 清单](../../discovery/mcp/reader.server.json)、[Scroll 清单](../../discovery/mcp/scroll.server.json)一致。初次发布遇 Registry 短期 JWT 已过期而返回 401；刷新认证后成功，没有重复登记或更换版本冒充成功。

## 社区申请及前序推送

未来内容检索计划已由 bb9b9d3 推送。DSH [开放插件市场 Issue #243](https://github.com/polang233/dsh-plugin-index/issues/243)与 [Awesome PR #12055](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/12055)已提交，均待审核，PR 检查仍运行。GitHub 集成没有外部仓库写权限，提交使用已有 gh 登录；没有重复申请。

## 验证边界

这是 Windows 上的清单与真实协议接入验证，不是某个宿主 MCPB 安装 UI 验证、跨机安装、理解质量测评或新增视频能力。本批无 B 站联网验证、发信、来信同步、日轮或调度修改。连续自动化、Qwen 中文退化等旧限制不据本次目录发布宣称解决。

官方 Registry 提供按名称的子串检索和版本元数据，不等于所有 Agent 已接入，也不等于语义检索/官方质量背书。具体查询及安装前提见 [MCP Registry 指南](../../docs/mcp-registry.md)。
