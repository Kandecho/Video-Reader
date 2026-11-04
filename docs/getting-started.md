# 第一次使用 Video Reader

目标是完成一件事：让你正在用的 AI 助手读取一条视频，并能按时间点继续讨论。

当前发布版支持 Windows x64，使用 PowerShell 7 和 Python 3.12。先准备依赖、安装 Reader，再接入 Codex 或 Claude Code。

## 1. 准备依赖和源码

需要能在 PowerShell 中找到下列程序。安装方法可从各自官方页面查看：

| 依赖 | 用途 |
|---|---|
| [PowerShell 7](https://learn.microsoft.com/powershell/scripting/install/installing-powershell-on-windows) | 运行安装和启动脚本 |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | 准备 Python 环境和依赖；需要时下载 Python 3.12 |
| [FFmpeg / ffprobe](https://ffmpeg.org/download.html) | 读取媒体、抽取画面和音频 |
| [Node.js](https://nodejs.org/en/download) | 读取 YouTube 时需要 |

如果不能让 uv 下载 Python，先自行安装 Python 3.12。FFmpeg 解压后，需要把包含 `ffmpeg.exe` 和 `ffprobe.exe` 的目录加入 PATH。

打开 [下载页](https://github.com/Kandecho/Video-Reader/releases/tag/v0.10.0rc6)，下载 `video-reader-0.10.0rc6-source.zip` 并解压。以下命令都在解压后含有 `bootstrap.ps1` 的目录执行；目录可以包含中文和空格。

## 2. 安装并检查

在该目录打开 PowerShell 7，运行：

```powershell
& './bootstrap.ps1'
& './run.ps1' doctor
```

安装脚本准备独立 Python 环境、初始配置，以及 Codex / Claude Code 的接入文件。它不会下载语音模型，也不会覆盖已有配置。

`doctor` 用来检查依赖。此时缺少 Whisper、Qwen 或语音模型并不意外；先用有可用字幕的视频完成第一次读取。若找不到 FFmpeg / ffprobe，先处理 PATH，再继续。

## 3. 接入你使用的助手

只执行所用助手对应的一组命令。它们需要该助手的命令行程序已经安装，并在同一个 Reader 安装目录中执行。

### Codex

```powershell
codex plugin marketplace add (Join-Path (Get-Location) 'integrations/codex')
codex plugin add video-reader@video-reader-local
```

### Claude Code

```powershell
claude plugin marketplace add (Join-Path (Get-Location) 'integrations/claude')
claude plugin install video-reader@video-reader-local
```

完成后让助手重新加载插件和 MCP 连接，再开始视频讨论。接入文件会指向这次安装的 Reader；模型和材料仍留在同一安装中。

如果使用其他支持 MCP 的助手，或需要检查接入细节，见 [操作与接入参考](reader-reference.md)。DSH 可按 [手动 MCP 接入指南](dsh.md)试用；已验证本机 0.2.2-rc.1 的 CLI 读图与续读，尚未提供一条命令安装的 DSH bundle。

## 4. 读第一条视频

先选择一条你有权访问、带有可用字幕的视频。向助手贴出完整链接，再说你想了解什么，例如：

> 读这条视频，整理作者的主要观点和论据，标出关键时间点。重要细节请对照画面。

接着可以直接追问：

> 06:12 那张图说明了什么？和字幕一致吗？

> 继续看后半段，补上尚未覆盖的部分。

> 把这次讨论引用的原话和画面导出，方便以后回查。

第一次准备长视频可能需要等待；助手应能报告进度并继续取得结果。你无需反复重新提交同一视频，也不用手动翻找缓存。

## 5. 按需要补齐

- **B 站要求登录**：让助手调用 Reader 的扫码登录，使用你打算给该组件使用的账号；它不跟随浏览器切换账号。
- **YouTube 需要 Cookie**：按 [安装与配置](installation.md#平台登录) 导入你手动导出的短期文件。过期后需要替换。
- **没有字幕**：按 [本地转写说明](installation.md#没有字幕时配置语音转写) 安装可选依赖并配置模型，安装基础包不会自动具备它。
- **助手找不到工具**：先确认安装命令成功，再重新连接 MCP。移动过 Reader 目录时，按 [迁移说明](installation.md#更新迁移和回退) 重新生成接入文件。

不接入助手、直接使用命令行的方式见 [CLI 与 MCP 参考](reader-reference.md)。更多文档见 [文档首页](README.md)。
