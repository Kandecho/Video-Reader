# 在 DSH 中接入 Video Reader 整包

DSH 适配器 **0.1.0** 接入同一安装中的 Reader、通用队列/历史和 Scroll。Reader 与 Scroll 分别提供 MCP；队列仍由独立的 `reading_tasks` 管理，通过 Reader 的 `video_tasks` 暴露。先按 [首次使用](getting-started.md)准备核心，并让 `doctor` 通过。当前支持 Windows，实测 DSH **0.2.2-rc.1**、核心 **0.10.0rc6**。

## 安装薄包

也可以先订阅[项目插件索引](discovery.md)，让 DSH 的发现页或 `plugin_market` 查到版本、仓库和固定 Git 安装参数；下面保留 Release tgz 的直接安装方式。

源码与适配器在[同一发布页](https://github.com/Kandecho/Video-Reader/releases/tag/dsh-video-reader%400.1.0)提供。薄包只装连接配置，不复制核心、凭据、模型或材料。请把目录改为你的实际安装位置：

```powershell
$env:VIDEO_READER_ROOT = 'D:/tools/Video Reader'
dsh plugin --profile web add 'https://github.com/Kandecho/Video-Reader/releases/download/dsh-video-reader%400.1.0/dsh-video-reader-0.1.0.tgz'
dsh web
```

已运行的 DSH 需要退出后从这个终端重新启动；仅刷新页面不会更新进程的环境变量。下次从另一个终端启动时，也需设置 `VIDEO_READER_ROOT`。如使用自定义配置，可另设绝对路径 `VIDEO_READER_CONFIG`；两套 MCP 共用它。未设置核心目录时，适配器会明确提示该变量缺失。

安装不会启用定时任务，也不会授权发送私信或评论。独立 B 站账号、收件、队列和授权投递的真实可用状态，以及仍在试用的自动化，见[能力状态](capabilities.md)。当前未发布 npm 包或提交插件索引，使用上面的 tgz 地址安装。

源码开发时，可在 `adapters/dsh` 执行 `npm pack`，再把 tgz 的绝对路径传给 `dsh plugin --profile <name> add`。卸载用 `dsh plugin --profile web remove dsh-video-reader`，重启后生效；共享核心及记录保留。

## 手动配置备选

已有 bundle 时不要再重复添加同名 MCP。只需 Reader 的维护者仍可手动创建以下 patch，替换成同一核心的实际目录；这条备选不会连接 Scroll。

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
        failOnStartupError: true
```

接入文件不需要填 B 站凭据。Reader 继续使用自己的配置、登录、模型与材料；普通读片不必连接 Scroll。

DSH 可用 `--patch` 加载该文件，例如：

```powershell
dsh --profile headless --patch 'D:/tools/reader.patch.yml' '读取这个视频，给三个带时间的要点：https://www.bilibili.com/video/BV...'
```

请替换为真实链接。模型应能调用 `mcp__video_reader__video_open` 等工具。未出现工具时，查看 DSH 启动日志，核对 Python、脚本和配置文件的绝对路径。DSH 的 stdio 协商会启动探测进程，随后启动服务进程，不应把两个启动过程视为两次读片。

## headless 的模型登录

当前 DSH headless 默认不读取 GUI 保存的凭据。若要使用已有 DSH 登录，按官方说明在这个 patch 中另加：

```yaml
- id: credentials
  disabled: false
- id: authorization
  disabled: false
- id: deepseek-account
  disabled: false
```

这是启用 DSH 自己的凭据服务；不要把账号密钥写入 Reader patch。若使用 API 环境变量，则沿用 DSH 官方的环境变量配置。没有可用模型登录时，Reader 工具连接成功也不能代替模型验收。[官方 headless 凭据说明](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/bundle/headless/README.zh.md#credentials)。

## 确认第一次读取

先发一条可访问的视频链接，要求带时间的要点，再追问某个画面。模型路由必须支持图片，才可核对原生帧；文本模型不能因工具返回图像就宣称看过。

长操作可以先返回 job。继续查询同一 job 并取得 result；有游标时按任务继续读取，避免重复 open。精确取帧的 `timestamps` 参数是列表，如 `["2", "6"]`。更多参数见 [Reader 参考](reader-reference.md)。

脚本化调用可加 `--json`，保存开头 session 事件中的 sessionId；同一目录与 profile 再用 `--session-id` 继续。headless 的事件投影会截断长字符串，验收不能仅靠日志中的摘要判断模型实际收到多少材料。

已安装整包的实际调用与发布证据见 [薄包验证](https://github.com/Kandecho/Video-Reader/blob/main/validation/dsh-bundle-20261104/report-source.md)；此前 Reader 手动接入的精确帧和会话恢复见 [前期实测](https://github.com/Kandecho/Video-Reader/blob/main/validation/dsh-integration-20261104/report-source.md)。当前验证不代表 web/desktop GUI、全部模型或其它操作系统均已验证。
