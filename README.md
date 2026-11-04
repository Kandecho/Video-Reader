# Video Reader

把 Bilibili、YouTube 和本地视频交给你正在用的 AI 助手阅读：整理内容、核对画面，或带着时间点继续追问。

Video Reader 提供字幕、语音和画面材料，通过 MCP 接入 Codex、Claude Code；理解和回答由助手完成。你可以直接贴链接提问，不必先生成笔记。

**[开始使用](docs/getting-started.md) · [下载 0.10.0rc6](https://github.com/Kandecho/Video-Reader/releases/tag/v0.10.0rc6) · [文档](docs/README.md)**

## 可以用来做什么

- **读懂一条视频**：“整理这条视频的主要观点和论据，标出值得回看的位置。”
- **核对具体细节**：“06:12 的图和讲解一致吗？把相关画面拿出来看。”
- **接着讨论或保存**：“继续上次没看完的部分，把引用的画面和原话一起导出。”

还可以按主题找 B 站视频、预览分镜，以及按需读取评论、回复和弹幕。长视频可以分次阅读，已取得的材料可继续使用。

## 开始使用

当前发布版面向 **Windows x64、PowerShell 7 和 Python 3.12**。安装需要 uv、FFmpeg / ffprobe；读取 YouTube 时还需要 Node.js。uv 可按需准备 Python。

下载并解压源码包，在解压后的目录打开 PowerShell 7，运行：

```powershell
& './bootstrap.ps1'
& './run.ps1' doctor
```

然后按 [首次使用指南](docs/getting-started.md) 接入你的助手，贴一个视频链接并说明你想了解什么。安装不会自动下载语音模型；没有可用字幕的视频，需要另行 [配置本地转写](docs/installation.md#没有字幕时配置语音转写)。

## 先了解这些边界

- **处理默认在本地进行。** Gemini 云端读取默认关闭，不会在失败后自动切换到云端。交给助手的材料由你选择的宿主和模型处理。
- **字幕和机器识别可能出错。** 重要细节可以回到原话、原图核对；取样画面不能保证覆盖每个短暂动作。
- **平台访问需要相应权限。** B 站使用组件自己的扫码登录；YouTube 可导入你手动导出的短期 Cookie。登录和平台限制仍可能影响读取。

本版的已知限制和验证范围见 [发布说明](RELEASE_NOTES.md)。

## 按需要查文档

| 你想做什么 | 从这里开始 |
|---|---|
| 第一次安装、接入助手、读一条视频 | [首次使用](docs/getting-started.md) |
| 设置模型、登录或调整文件位置 | [安装与配置](docs/installation.md) |
| 查命令、工具参数、续读和导出 | [CLI 与 MCP 参考](docs/reader-reference.md) |
| 管理待读视频、附言和结果 | [队列与历史](docs/tasks.md) |
| 使用个人推荐、私信收件和授权投递 | [Scroll](docs/scroll-reference.md) |
| 报告问题或参与开发 | [贡献与复现](CONTRIBUTING.md) |

Scroll 是可选的个人工作流，普通读片无需配置它。[文档首页](docs/README.md)还列出了完整参考和维护入口。

## 许可

项目原创代码采用 [MIT](LICENSE)。第三方代码、依赖和模型保留各自许可，见 [第三方声明](THIRD_PARTY_NOTICES.md)。源码包不含用户视频、私信、凭据或模型。
