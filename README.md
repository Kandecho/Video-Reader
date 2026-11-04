# Video Reader

让 Agent 像使用图文一样使用视频：读取字幕与画面、定位疑点、继续追问，并回查原始材料。可以先看再聊，也可以带着问题深入；不需要先生成笔记。

核心版本 **0.10.0rc6**，Codex / Claude Code 薄适配器 **0.5.5**。原创代码采用 [MIT](LICENSE)，第三方归属见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)。这是 Windows 源码预发布版。

## 安装与第一次读取

已验证的基础环境是 Windows x64、Python 3.12、PowerShell 7，以及 PATH 上的 FFmpeg / ffprobe。YouTube 下载还需要 Node。安装需要 uv 和网络；模型、平台账号及可选 GPU 环境单独配置。

解压源码包后，在其目录运行：

```powershell
& './bootstrap.ps1'
& './run.ps1' doctor
& './run.ps1' open 'D:\Videos\example.mp4'
```

Bootstrap 创建本目录的 `.venv`、初始 `config.json` 和两套薄适配器。默认安装 MCP 与 OCR 依赖，不下载语音模型；已有配置保留。目录可包含中文和空格，也可从其他工作目录调用脚本。

`open`、`read`、`transcript` 等长操作默认短等待返回 `job_id`。继续使用同一任务：

```powershell
& './run.ps1' job status 'j_任务ID'
& './run.ps1' job result 'j_任务ID' --wait 10
```

使用返回的实际 ID。材料分页优先沿 `delivery.next_cursor` 续读；MCP 返回原生图片，CLI 图片路径需要宿主实际打开。完整参数、返回状态和来源约束见 [Reader 参考](docs/reader-reference.md)及[材料与续读](docs/material-delivery.md)。

## 三个使用例子

- **完整学习**：“详细读这条视频，保留主要论证与必要画面。”宿主读取全部所选语音及必要视觉，再组织回答。
- **定向核对**：“核对 06:12 的示意图，字幕和画面是否一致？”宿主读取该区间、精确取帧，按疑点深入。
- **继续与复用**：“接着上次的 session 看后半段，把引用依据导出。”共享材料、时间、游标和校对历史可跨会话复用。

足以支持当前回答时及时回答。处理完成、材料已交付、宿主实际观察、语义校对完成及识别准确是不同判断。原始文本、疑点与未核查部分保留，不以摘要替代原文。

## 接入宿主

两套适配器共用同一安装、模型、登录与材料；插件中不复制阅读核心。

```powershell
# 使用实际解压目录中的 integrations 路径
codex plugin marketplace add 'D:\tools\Video Reader\integrations\codex'
codex plugin add video-reader@video-reader-local

claude plugin marketplace add 'D:\tools\Video Reader\integrations\claude'
claude plugin install video-reader@video-reader-local
```

只执行所用宿主的命令；上面的路径是示例。更新或移动核心后重新运行 `tools/build_plugins.py`，再刷新宿主连接以加载新工具。需要直接接入 MCP 时，使用生成适配器里的 `.mcp.json`。Reader 20 个工具，Scroll 7 个工具。

## 组件边界

| 部分 | 职责 | 入口 |
|---|---|---|
| Reader | 获取、字幕 / ASR、画面、局部复听、原文与校对存取、续读与导出 | `run.ps1`；[阅读 Skill](skill/SKILL.md) |
| 通用任务 | 队列、附言、分流、显式批读、结果及任务历史 | `tasks.ps1`；Reader `video_tasks`；[任务参考](docs/tasks.md) |
| Scroll（可选） | 个人推荐与反馈、私信 Inbox、原消息历史、授权汇报与投递 | `scroll.ps1`；[Scroll 参考](docs/scroll-reference.md) |
| 宿主 Agent | 理解、语义校对、跨资料推理、决定补看和形成回答 | 当前会话 |

普通读取无需初始化 Scroll。收件同步、队列管理、安装和阅读不自动创建轮询、调度或发送消息。通用任务与 Reader job 各有状态；缓存存在不表示任务已读完。

## 平台、模型与限制

- 支持本地视频、Bilibili 链接 / BV / 分 P，以及 YouTube。字幕优先，无字幕时可用本地 Whisper；模型需按说明取得和校验。
- Bilibili 使用组件独立扫码登录。YouTube 可导入用户导出的短期 Cookie，失效后需重新导出；不保证长期登录维持。
- Qwen 是显式可选来源，不是默认或失败回退。独立环境与 GPU、模型需要另配；已知强制中文退化问题见发布说明。
- Gemini 默认关闭；失败不自动转云端，也不读取其他视频应用的配置或凭据。
- Reader 提供材料与差异线索，首次读取不自动得到独立语义初校稿。连续动作、短暂事件和声音语义不能仅凭取样、字幕或音量测量下结论。
- 评论与回复支持分页；弹幕可选。可见材料不等于删除、隐藏或历史全量；末页计数歧义会保留不完整状态。

完整安装、独立配置 / 缓存路径、可选模型与移位说明见 [安装文档](docs/installation.md)。本版声明范围及已知限制见 [发布说明](RELEASE_NOTES.md)。

## 复现、更新与贡献

源码包不含凭据、真实配置、模型、虚拟环境、用户视频、私信或私人任务结果。Python、FFmpeg / ffprobe 和 Node 均为外部依赖。

```powershell
& './bootstrap.ps1' -Features mcp,vision,asr
& './.venv/Scripts/python.exe' -m unittest discover -s tests -v
& './.venv/Scripts/python.exe' examples/create_fixture.py 'D:\Temp\Video Reader fixture'
```

合成样本不需要账号或语音模型，覆盖中英文字幕、画面冲突、续读和导出。它没有音轨，字幕里的指令式句子仍只是材料。

更新到新目录并验证后再切换宿主路径，保留原目录及共享配置 / 模型 / 缓存，方便回退。问题模板与操作细节见 [贡献与复现](CONTRIBUTING.md)。维护记录和历史验收位于 [公开仓库](https://github.com/Kandecho/Video-Reader) 的 `docs/`、`planning/` 与 `validation/`。
