# DSH 接入与发现路径考察

日期：2026-11-04。结论：**现有 Reader 可以沿官方 MCP 客户端设计薄接入；若希望被 DSH 的插件检索发现，还需要可安装的 bundle 和索引收录。** 本轮完成源码核查、Reader 端合约测量和配置草案，尚未在 DSH 中安装或完成端到端验收。

## 依据与适用版本

- 官方仓库固定在 [8bd0733](https://github.com/deepseek-ai/deepseek-harness/tree/8bd073392eef6f54e921a093b95076248eb08cbb)，源码包版本为 0.2.2-alpha.3。选取 13 个源码、配置及说明文件，核对了 Git blob 指纹。
- 本机安装的 DSH、MCP 客户端和插件市场包均为 **0.2.1-rc.5**。只读核对了启动器、包元数据、MCP 客户端实现和市场说明，没有读取用户 profile 或凭据，也没有升级 DSH。
- 本机客户端已含 stdio、图片接纳和任务扩展拒绝逻辑，市场包说明也确认默认没有索引源。它与固定源码并非同一版本，正式适配仍需选定并实测目标版本。
- 10 月 31 日的生态扫描保留为当时的线索。本次据官方代码判断接入与发现机制，不据旧市场列表判断当前竞品能力或流量。

## 1. 最短接入路径：Reader MCP

官方客户端接受 `command`、`args`、`env`、`cwd` 的 stdio 配置，并把工具命名为 `mcp__<serverName>__<工具名>`。现有 Python 核心、模型、登录和材料继续共用，第三个宿主只增加连接配置。依据：[配置 schema](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/mcp/mcp-client/src/index.ts#L161)、[工具命名](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/mcp/mcp-client/src/tools.ts#L91)。

下面是**本地配置草案**，使用示例安装路径，未写入任何 DSH profile。外层 `insert` 结构参照官方 MCP 模板；部署时应由安装位置生成实际路径。

```yaml
- insert:
    - id: video-reader-mcp
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: video_reader
        transport: stdio
        command: 'D:/tools/Video Reader/.venv/Scripts/python.exe'
        args: ['-I', 'D:/tools/Video Reader/launch_mcp.py']
        env:
          VIDEO_READER_CONFIG: 'D:/tools/Video Reader/config.json'
          PYTHONIOENCODING: 'utf-8'
        startupTimeoutMs: 60000
        toolCallTimeoutMs: 60000
```

建议首次只接 Reader；Scroll 的推荐、私信和投递作为单独的可选配置。Python / FFmpeg、平台账号和模型仍需准备，安装一个 DSH bundle 不会自动完成这些步骤。官方 [配置型 bundle 示例](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/preset/agent-preset/skills/cordis-plugin-development/templates/mcp/cordis.patch.yml)可作为后续生成器依据。

### Reader 端已实际测量

隔离配置下，仅对公开合成视频运行 MCP 初始化、工具发现和一次打开；没有复用现用账号或用户材料。

| 项目 | 测量值 | 对适配的含义 |
|---|---|---|
| Reader 工具 | 20 个 | 现有工具可作为连接对象 |
| 协议版本 | 2025-11-25 | 已有服务端协议事实，DSH 侧仍须完成实际协商 |
| 服务指令 | 6,971 UTF-8 字节 | 小于 DSH 默认 32,768 字节上限 |
| 加上 namespace 后的工具名 | 最长 40 字符，字符均合法 | 符合 DSH 64 字符约定，无需名称截断 |
| 强制 MCP task 扩展 | 0 个工具 | `video_job` 是普通工具，不要求 DSH 尚未支持的 task 扩展 |
| 原生图像 | 2 个 JPEG 块，base64 规范 | Reader 输出符合 DSH 已实现的栅格图片格式范围 |

这些是 **Reader 端合约检查**，没有冒充 DSH 端到端通过。DSH 对 task 扩展的限制见 [执行器](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/mcp/mcp-client/src/tools.ts#L301)。

## 2. 真正需要验证的适配点

**图片进入模型有条件。** 官方代码要求附件存储已挂载，并解析当前实际 provider / model，确认模型声明支持 image 输入。否则返回图片不可用的诊断，原始块只供程序调用方使用。不能只看到工具出现或文字返回，就宣称 DSH 已经看到了视频画面。依据：[图片接纳](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/mcp/mcp-client/src/tools.ts#L378)。

**长处理与连接恢复要分别验证。** Reader 的 open/read/transcript 默认短等待返回，后续沿同一 job 和材料游标继续。DSH 的连接重连不代表业务任务完成；测试应包括模型跟进已有 job、继续读取、保持原始材料和明确的失败状态。客户端会先探测再建立正式 stdio 进程，启动过程应保持无投递等业务副作用。依据：[官方客户端说明](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/mcp/mcp-client/README.zh.md)。

**环境与权限保持显式。** DSH 清洗父进程中的凭据形态变量及 DSH_* 后合并配置 env，因此应明确设置 Reader 配置路径，不依赖偶然继承。Reader 的平台登录继续归自身管理。MCP 服务器指令可承载现有阅读约定；Codex / Claude 的插件清单不会自动成为 DSH 的插件。依据：[子进程环境](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/mcp/mcp-client/src/transport.ts#L15)。

后续正式验收应在专用 profile 上覆盖：工具发现、模型实际看图、文字与画面冲突、长 job 查询、游标续读、连接重建、错误和本地资源复用。首版接入不需要新增阅读核心、守护进程或自动私信流程。

## 3. 接入之后，怎样进入 DSH 的发现路径

当前官方的自定义插件索引功能默认关闭，**默认不配置索引源**。启用相应功能和预设后，界面与只读 `plugin_market` 工具查询的是用户配置的索引；它们不会自动遍历 GitHub。这里说的是默认行为，本轮没有查询用户实际配置了哪些源。依据：[官方索引指南](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/docs/user/guide/plugin-market.zh.md#L19)、[工具约定](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/boot/plugin-market/src/tools.ts#L62)。

索引搜索读取包名、各语言的标题与描述、关键词、作者及分类标签。当前实现对名称 / 标题加权 3，关键词加权 2，并采用前缀和模糊匹配；查询各词按 AND 组合。README 全文不在这组索引搜索字段里。依据：[搜索实现](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/packages/boot/plugin-market/src/search.ts#L95)。

因此有三项具体缺口：

1. **可安装的 DSH 薄 bundle。** 当前仓库是 Python 项目，没有可发布的 DSH bundle manifest。需要声明 `dsh.bundle.patch`，提供面向用户的标题、说明和安装前提。公共包不能保留官方本地模板中的 `private: true`。
2. **可识别的版本和路径。** 官方参考生成器支持根包、workspace 包或三层目录内的 bundle。发布版本使用严格 SemVer；当前 Python 核心的 `0.10.0rc6` 不能直接当作 bundle 的 SemVer 版本，需要明确适配器自身版本。
3. **目标索引源收录。** 需要把 bundle 纳入用户会采用的索引，或由用户添加明确的自建索引。公开仓库或发布 npm 包本身不会自动出现在每个用户的 DSH 中。

以上规则及元数据来源见 [官方索引生成器](https://github.com/deepseek-ai/deepseek-harness/blob/8bd073392eef6f54e921a093b95076248eb08cbb/apps/plugin-market-generator/README.zh.md#L41)。这也说明索引收录应接在可安装性验证之后，避免搜索结果指向尚不能完成安装的入口。

## 4. 对后续 GEO 讨论的建议

把目标分为三个可观察的入口，分别决定动作：

| 入口 | 当前需要讨论什么 |
|---|---|
| DSH 插件检索 | 先做薄 bundle 与目标索引收录；标题、双语描述和关键词围绕实际用途填写 |
| Agent 的 GitHub / Web 检索 | 明确希望命中的任务问法，再检查 About、topics、标题和公开示例是否提供足够线索 |
| 找到仓库后的选择与使用 | 人类 README 说明用途，首次使用指南说明成本和步骤；Agent 技术参考提供可验证的工具与限制 |

本次核对仓库 About 描述仍为 “A general tool to help agent read video better”，topics 为空，homepage 为空。这是元数据快照，不证明仓库未被索引，也不代表任何搜索排名。当前改动首先完成面向人的文档入口，没有顺带修改 GitHub topics、发布 npm 包、提交索引或做流量承诺。

GitHub 的仓库搜索在未指定 `in` 时，只搜索名称、描述和 topics；搜索 README 内容需显式使用 `in:readme`。这使 README 的人类可读性与默认检索字段成为两个应分别处理的工作。依据：[GitHub 搜索规则](https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories#search-by-repository-name-description-or-contents-of-the-readme-file)、[topics 用途](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/classifying-your-repository-with-topics)。

本次通过 GitHub 仓库搜索做了两条限定本仓库的字段测试，结果如下。测试发生在本次文档推送及任何元数据修改之前；它检验当次能否命中，不评估全站排名。

| 查询 | 是否返回本仓库 |
|---|---|
| `repo:Kandecho/Video-Reader bilibili mcp` | 否 |
| `repo:Kandecho/Video-Reader bilibili mcp in:readme` | 是 |

下一步讨论可以从一份具体元数据草案开始，实施前仍需确定取舍：

- About 候选：`MCP video reader for Bilibili, YouTube and local files: timestamped transcripts, frame inspection and resumable reading, with local processing.`
- Topics 候选：`mcp-server`、`video-reader`、`bilibili`、`youtube`、`ai-agents`、`local-first`。
- 验证方式：先保留字段测试，再增加少量真实任务问法，分别检查 GitHub 默认检索、显式 README 检索和目标 Agent 的实际检索路径。元数据更新后等待索引变化再复查，不能把刚保存成功当作效果验收。

下一步可用少量真实问法建立基线，例如“给 Agent 读取 B 站视频并按时间点看原图”“YouTube 字幕与画面核对 MCP”“本地视频可继续追问的阅读工具”。讨论应先选目标入口和成功标准，再决定元数据、示例或 Agent 专用说明，不把多放关键词或增加一个文件等同于可发现性提升。

## 本轮产物与验证范围

面向人的 README、文档首页、首次使用和安装参考已整理；README 为 53 行，CLI / MCP 诊断细节移至操作参考后部，原有参考段落完整保留。10 份文档共 180 个本地链接与标题锚点检查无缺失，源码分发回归 1 项通过，并用本机 CLI 帮助核对接入命令。没有修改读取实现，本轮不重复全套视频处理测试。

源码样本、指纹、Reader 合约测量和本机包核查证据留在 data/docs-geo-20261104；公开汇总见同目录 summary.json。未启动 DSH、未改 profile、未安装第三套适配器、未发送消息或新增调度。
