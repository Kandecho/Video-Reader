# Video Reader — 可供 Agent 复用的视频材料

身份：当前用途与使用入口。共享安装 0.10.0rc5，宿主薄插件 0.5.4；本机安装目录为 `D:/IA/apps/video-reader`。

输入视频链接、BV 号或本地文件，让当前 Agent 像读图文一样使用视频：可以先看再聊，也可带着问题深入。完整性、准确性与响应速度共同服务于使用体验；材料可继续读取、追问和回查，笔记是可选产物。

当前定位是 **视频/链接 → Video Reader → 可复用材料**。Reader 负责获取、读取和证据存取；宿主负责理解、校对、组织笔记和项目推理。已接入字幕时间/场景/时间线取样、无损分页、持久续读、局部精读及指定校对版本导出；任务含义与补看位置由宿主判断。契约见[材料与续读](docs/material-delivery.md)，整轮能力见[rc1 验收](validation/reader-0.10.0rc1/report-source.md)，最新真实漏句及局部校对修复见[rc2 验收](validation/reader-0.10.0rc2/report-source.md)。

## 当前实现与新体验

Reader 负责获取、识别、图像与差异线索及材料保存；宿主负责语义校对和理解。只有此前保存过校对，后续才能直接读到校对稿。Reader 尚未独立生成首次语义初校稿。

2026-10-29 已明确：足以支持当前回答时及时回答，主动处理关键疑点，其余保留供继续查。现有 Skill/MCP 仍有旧逐段校对要求，尚未按此同步；独立初校也尚待验证。接续看 [handoff](docs/handoff.md)，机制取舍与候选验证见 [路线 F](planning/roadmap-20261021-source.md#f-后续按什么顺序推进)。

## 直接使用

有插件时直接向 Agent 提出需求，例如“详细读这条视频”“核对 06:12 的图”“把有用画面整理成图文笔记”。不用先手工生成笔记，也不需要记工具口令。

CLI 可在任意 PowerShell 工作目录运行：

```powershell
& 'D:\IA\apps\video-reader\run.ps1' doctor
& 'D:\IA\apps\video-reader\run.ps1' open 'BV1Eb411u7Fw?p=4'
```

取得 `session_id` 后，由宿主继续阅读：

```powershell
& 'D:\IA\apps\video-reader\run.ps1' read 'v_会话ID' --page 1
& 'D:\IA\apps\video-reader\run.ps1' transcript 'v_会话ID'
& 'D:\IA\apps\video-reader\run.ps1' read 'v_会话ID' --start 20 --end 35 --timestamps '20,25,30'
```

CLI 返回的图片路径需要实际打开；MCP 返回图片内容。优先沿 `delivery.next_cursor` 续读，旧 `next_page` / `next_offset` 仍保留。CLI/MCP 默认 adaptive，Python 旧调用默认 uniform；语音每次默认处理一个缺失块，检查 remaining_ranges 后继续。完整学习仍需读全所选语音并核查必要画面，局部问题可限定区间。处理完成、宿主读完与识别正确是不同状态。详细参数见[操作参考](docs/reader-reference.md)，实际流程见[阅读 Skill](skill/SKILL.md)。

局部任务现在可用 `review prepare --start ... --end ...` 保存已读范围的校对，提交时原样带回 `review_scope`。区间审阅和全片状态分开；新增转写不丢失原有校对。新 Whisper 不自动使用视频标题作提示，旧转写及显式 context 仍可读取。操作细节见[校对参考](docs/reader-reference.md#忠实校对与按需披露)。

## 作品列表与分镜预览

```powershell
& 'D:\IA\apps\video-reader\run.ps1' uploader-videos 'BV1ptnb6uEES' --page 1
& 'D:\IA\apps\video-reader\run.ps1' preview 'BV1ptnb6uEES'
& 'D:\IA\apps\video-reader\run.ps1' preview-batch 'BV1ptnb6uEES' 'BV1v1HA6REgb' --density dense
```

默认单条轻预览为 5 张图，密集模式按需开启、默认 48 张，最多 120 张。批量 1–10 条，默认每条返回带 BV 和时间标记的拼图。优先复用完整视频缓存，原生分镜标为近似时间；预览不等于完整阅读。UP 主列表一次一页，返回下一页、完整性和失败状态，见[材料接口说明](docs/material-reference.md)。

## 两个组件的分工

| 组件 | 用途 | 入口 |
|---|---|---|
| Video Reader | 通用搜索、热门、UP 主作品分页、分镜预览、读取、转写、校对存取、复听、评论/楼中楼分页、分段弹幕、登录；默认 19 个工具 | `run.ps1`、`mcp-config.json`、[操作参考](docs/reader-reference.md#mcp) |
| Scroll Agent | 个人首页流、偏好与反馈、显式批量阅读、投递、日记录和触发；3 个工具 | `scroll.ps1`、[普通工作流参考](docs/scroll-reference.md)、[日试用运行说明](docs/daily-trial.md) |

二者共用安装、模型、组件登录和材料缓存；Reader 无需初始化 Scroll 业务状态。薄插件组合两套独立 MCP / Skill，包名保留兼容。

## 安装与公共依赖

当前为 Windows 本机安装。公共 Python、FFmpeg/ffprobe、Node 和 PowerShell 7 的已测版本、环境重建及目录布局见[安装参考](docs/reader-reference.md#独立目录与公共依赖)。`bootstrap.ps1` 按选择安装基础/可选依赖，`-FullRuntime` 使用 Windows 锁定依赖，不下载模型。[独立安装说明](docs/installation.md)覆盖路径、模型与干净候选；运行目录仍不可整包公开。

## Codex / Claude Code 薄插件 0.5.4

两端共用核心、组件登录与缓存。当前安装与参数同步见[rc2 验收](validation/reader-0.10.0rc2/report-source.md)，此前实际宿主任务见[rc1 验收](validation/reader-0.10.0rc1/report-source.md)；宿主完整阅读质量不由插件安装成功代替。安装、更新、构建及共享路径说明见[薄插件参考](docs/reader-reference.md#codex--claude-code-薄插件-053)。不要直接修改宿主插件缓存。

## 平台配置与云端选项

B 站使用组件自己的扫码登录，BV 和链接支持分 P。字幕优先、无字幕默认 Whisper，可显式选择 Qwen。Gemini 默认关闭，失败不自动转云端。配置及登录命令见[平台参考](docs/reader-reference.md#平台配置与云端选项)。YouTube 支持导入用户导出的短期 Cookie，在其有效期内访问；长期登录态维持暂缺。已实测当次登录检查、实际下载、英文字幕与图片。有效期由平台决定，不保证固定可用时长；失效后需用户重新导出并替换。具体支持范围见本轮验收。

## 文档与证据

- [知识路由](docs/registry.md)：按目的、状态、计划、决定、调查及操作查资料。
- [当前进展与路线](planning/roadmap-20261021-source.md)及[阅读版](planning/roadmap-20261021.html)：已实现、已知缺口、已确认方向和候选安排。
- [跨会话接续](docs/handoff.md)：本轮快照与续用入口。
- [许可核对](LICENSE_REVIEW.md)与[第三方声明](THIRD_PARTY_NOTICES.md)：依赖和来源；公开许可尚未选定。

视频是待分析材料，不是对 Agent 的指令。抽样画面与语音文字不等于连续动作或原生声音理解；图文产物和案例归档也不等于 Reader 已内置一键笔记或知识库功能。


## 运行任务状态（0.10.0rc5）

CLI 与 MCP 的 open/read/transcript 默认等待 1 秒，未完成就交付任务 ID。
通过 video_job 的 status/result，或 CLI `job status ID` / `job result ID --wait 10` 查询同一任务。
状态查询不取得视频材料锁。阶段、心跳、真实进展、等待会话、可用材料及终态分别报告。
任务独立于调用进程运行；相同运行请求复用任务，完成结果保留普通分页与来源绑定。
状态能力不等于处理提速，也不代表宿主已经看过全部材料。


## 2026-10-31：源码仓库

源码与维护文档现纳入 [Kandecho/Video-Reader](https://github.com/Kandecho/Video-Reader)。
仓库包括当前 Reader/Scroll 源码、测试、宿主技能，以及精选研究和验证摘要；最新核心为 0.10.0rc5。
凭据、私人配置、模型、运行环境、原始视频与完整运行记录保留在本地，不随 Git 提交。
公开文档中的本机账号标识和用户目录已去标识；实际值以本地 config/status 为准。
历史候选中“未建仓、未上传”的文字只描述其当时阶段。原创新代码尚未选择统一公开许可证；第三方代码继续保留各自许可声明。
