# MCP Registry 与 MCPB 接入

Video Reader 与 Scroll 通过同一项目的两个 MCPB 接入包发布，共用已准备好的 Windows 核心、材料、任务和登录。Reader 提供视频材料以及通用队列/历史；Scroll 提供独立 B 站账号、个人推荐、Inbox 与授权投递。[能力状态](capabilities.md)区分已用能力和自动化试用范围。

## 安装前提

先按[安装参考](installation.md)准备核心，完成 `.venv/Scripts/python.exe`、`config.json` 和所需公共依赖。包本身不安装模型、运行环境或账号。核心仍为 0.10.0rc6，MCPB 接入包版本为 0.1.0，版本分别维护。

从 [mcpb-v0.1.0 Release](https://github.com/Kandecho/Video-Reader/releases/tag/mcpb-v0.1.0)取得 `video-reader-0.1.0.mcpb`、`scroll-agent-0.1.0.mcpb`，在支持 MCPB 的宿主安装所需服务，选择同一核心目录。可选配置文件留空时使用核心下的 `config.json`；另选配置文件时，两包选同一份才能共享状态。完整源码也随同一 Release 提供，包含 Reader、reading_tasks 和 Scroll。

本机通过官方 MCPB 清单校验及解包配置的真实 stdio 调用，包含中文/空格路径、本地视频、字幕分页、队列和 Scroll 离线状态。宿主的 MCPB 安装 UI 尚未验收；不支持 MCPB 的宿主可沿用[现有接入方式](getting-started.md)。安装不会自动同步 Inbox、发送或新增调度。

## 登记在哪里，如何查询

官方入口是 [MCP Registry](https://registry.modelcontextprotocol.io/)，服务名称为 `io.github.Kandecho/video-reader` 和 `io.github.Kandecho/scroll-agent`。2026-11-04 两个 0.1.0 已发布，公开 API 按发布者检索返回两条，精确 latest 查询均为 active、isLatest=true，包地址和摘要与本地清单一致。网页可按服务名称搜索 `Kandecho`、`video-reader` 或 `scroll-agent`。API 的名称查询是大小写不敏感的子串匹配，检索词至少三个字符；它不是按自然语言理解能力的语义搜索。[官方 API 说明](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/official-registry-api.md)。

- [查询本发布者的最新条目](https://registry.modelcontextprotocol.io/v0.1/servers?search=Kandecho&version=latest)。
- [Reader 最新登记](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Kandecho%2Fvideo-reader/versions/latest)。
- [Scroll 最新登记](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Kandecho%2Fscroll-agent/versions/latest)。

Registry 保存服务说明、来源、版本、分发地址和校验摘要，实际安装包在 GitHub Release，视频材料仍在本地。其他 Agent 或宿主需要主动查询这个 API，或使用接入它的目录/市场；登记不代表所有 Agent 会自动发现，也不保证下游目录同步时间或关键词排名。需要按能力检索时，下游目录可再做分类、关键词或语义检索。[官方消费方式](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/registry-aggregators.mdx)。

官方 Registry 当前仍标记为 preview，存在格式变化或数据重置的可能；发布成功表示元数据已进入目录，不表示官方认证视频理解质量或所有平台功能。[官方发布说明](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx)。

## 维护

清单在 [Reader](../discovery/mcp/reader.server.json) 和 [Scroll](../discovery/mcp/scroll.server.json)，薄包源在 [adapters/mcpb](../adapters/mcpb/README.md)。`tools/build_mcpb.py` 只打包四个公开文件；发布前用固定版本官方工具校验，核对 Release 资产 SHA-256，再串行发布两个 server.json，并从公开 API 回查最新版本与摘要。旧版资产不覆盖，后续修改包内容须递增版本。

本批结果见[登记验收](../validation/mcp-registry-20261104/report-source.md)。发布凭据使用官方工具的本地私有存储，不进入项目或源码包。
