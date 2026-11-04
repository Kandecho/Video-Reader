# 安装与配置参考

第一次使用，请先看 [首次使用指南](getting-started.md)。本页供需要配置模型、平台登录、文件位置或迁移安装的用户查阅。更多入口见 [文档首页](README.md)。

当前发布版是 0.10.0rc6，Codex / Claude Code 接入文件版本为 0.5.5。已测基础环境为 Windows x64、Python 3.12 和 PowerShell 7；其他系统和 Python 组合尚未完成安装验收。项目原创代码为 MIT，第三方许可分别保留。

## 基础安装与依赖

准备 PowerShell 7、uv 和 PATH 上的 FFmpeg / ffprobe。YouTube 下载还需要 Node.js。安装 Python 依赖和获取在线视频需要网络；已有本地材料可以离线使用。

在解压后的 Reader 目录运行：

```powershell
& './bootstrap.ps1'
& './run.ps1' doctor
```

默认安装基础、MCP 和 OCR 依赖。uv 可在需要时准备 Python 3.12，脚本随后建立本目录的 `.venv`，仅在缺失时创建 `config.json`，并按实际目录生成两套宿主接入文件。它不下载语音模型，也不复制其他安装的环境、账号或缓存。

按需要选择可选依赖：

| 用途 | 安装命令 |
|---|---|
| 不需要本地 OCR | `& './bootstrap.ps1' -Features mcp` |
| 需要 Whisper 转写，或运行完整测试 | `& './bootstrap.ps1' -Features mcp,vision,asr` |
| 按已记录的 Windows 完整依赖清单重建 | `& './bootstrap.ps1' -FullRuntime` |

没有 uv 时，也可自行用 Python 3.12 建立 `.venv`，用该环境的 pip 安装 `.[mcp,vision]`，仅在缺失时复制 `config.example.json` 为 `config.json`，再运行 `tools/build_plugins.py`。启动可用根目录脚本或已安装的命令行入口；不需要设置开发目录的 PYTHONPATH。

## 配置与文件位置

配置读取顺序为 CLI 的 `--config`、环境变量 `VIDEO_READER_CONFIG`、`VIDEO_READER_HOME/config.json`。未指定时，源码安装使用自身目录的配置；wheel 安装使用用户的 VideoReader 数据目录。

配置中的相对路径以**配置文件所在目录**为准，不随命令的工作目录变化。以下位置都可以另配到其他磁盘：

| 内容 | 配置项 |
|---|---|
| 已读取的视频和材料 | `cache_dir` |
| 分镜预览 | `preview.directory` |
| B 站登录 | `bilibili_auth.directory` |
| Whisper 模型 | `asr.model_path` |
| 可选 Qwen 模型与环境 | `qwen.model_path`、`qwen.aligner_path`、`qwen.runtime_dir` |
| YouTube Cookie 文件 | `platforms.youtube.cookies_file` |

模型、登录、缓存和配置可由不同宿主共用。分享源码时排除这些私有文件；要分享阅读依据，使用 [材料导出](material-delivery.md)，不要直接复制整个运行目录。

## 平台登录

**Bilibili** 使用 Reader 自己的扫码登录存储，不读取或跟随浏览器账号。需要时让助手启动登录、展示二维码，再由你使用目标账号扫码。

**YouTube** 支持用户手动导出的短期 Netscape Cookie 文件。把 `platforms.youtube.cookies_file` 指向该文件，用 `youtube-status` 检查当前情况；失败可能是网络或平台问题，不能直接当作已退出登录。Cookie 失效后需要重新导出并替换，目前没有长期自动维持方案。处理使用临时副本，不改写原文件。

不要把 Cookie、登录目录或含凭据的配置上传到问题报告或源码仓库。

## 没有字幕时配置语音转写

有可用字幕时不需要语音模型。无字幕或需要独立核对语音时，可安装本地 Whisper 依赖：

```powershell
& './bootstrap.ps1' -Features mcp,vision,asr
```

然后从模型发布方取得兼容 faster-whisper 的 CTranslate2 模型，把 `asr.model_path` 指向模型目录。默认在 CPU 上以 int8 运行。仅装 Python 包不会自动取得权重；没有本地模型时会报告不可用，不把它解释为视频无人声。

在安装目录的 `config.json` 中调整现有的 `asr.model_path`，例如：

```json
{"asr": {"model_path": "D:/Models/faster-whisper-medium"}}
```

源码附有 [Whisper medium 来源与校验清单](models/faster-whisper-medium.json)，记录发布方、固定 revision 和文件 SHA-256，不包含权重。按清单的 model 和 upstream_revision 下载对应文件，随后检查：

文件下载地址的形式为 `https://huggingface.co/<model>/resolve/<upstream_revision>/<filename>`，三个值均取自清单。

```powershell
& './.venv/Scripts/python.exe' tools/check_models.py docs/models/faster-whisper-medium.json 'D:\Models\faster-whisper-medium'
```

上面的模型路径是示例。检查不会联网或改写模型；缺少文件或校验不符会失败。选用其他模型时，需要它自己的来源与许可记录，不能沿用 medium 的哈希。

### 可选 Qwen

Qwen 需要明确选择 `source=qwen`，不会自动作为默认或失败回退。基础读取不依赖它；当前强制中文退化问题仍未修复，见 [发布说明](../RELEASE_NOTES.md)。

新安装的隔离环境默认位置为 `runtimes/qwen`，与 Reader 使用相同 Python 主次版本。已验证环境组合为 Python 3.12、qwen-asr 0.0.6、torch / torchaudio 2.10.0+cu128、transformers 4.57.6 和 accelerate 1.12.0。创建环境后，从官方 PyTorch cu128 源安装对应 GPU 包，再安装上述 ASR 依赖；ASR 与 ForcedAligner 模型另从发布方取得，并配置模型路径。

该选项需要兼容的 NVIDIA 驱动和显存。已有验证只涵盖本机一个短语音窗口；文件探测通过不等于 CUDA 可用。原安装仍兼容已有的 research 隔离环境，不要在新环境通过实际请求前删除它。运行时使用本地模型，失败不自动下载或转云端。

## 更新、迁移和回退

将新源码解压到新目录，建立环境，并显式配置要复用的模型、登录与数据路径。验证后再让宿主切换过去，保留原目录与配置以便回退。

移动核心后重新生成接入文件：

```powershell
& './.venv/Scripts/python.exe' tools/build_plugins.py
```

随后按 [首次接入步骤](getting-started.md#3-接入你使用的助手) 更新宿主并重新连接 MCP。回退时恢复此前核心和配置的指向，不删除共享缓存、模型、登录或校对记录。

移动缓存不会自动改写历史材料引用；可移位分享的交付物是完整导出目录，缓存迁移需单独处理。安装和更新不会自动启用推荐、私信、日推或新调度。

## 开发与发行记录

测试、复现和源码候选构建见 [CONTRIBUTING](../CONTRIBUTING.md)。本版具体范围见 [发布说明](../RELEASE_NOTES.md)，历史验收保留各自版本和日期；当前主分支文档可能晚于下载包中的文档快照。
