# 在 DSH 中手动接入 Reader

这条路径已在本机 Windows、DSH **0.2.2-rc.1**、Reader **0.10.0rc6** 上实际验证，包括读图、任务查询和会话续读。当前提供手动 MCP 接入，还没有可通过 `dsh plugin add` 安装的 Video Reader bundle。先按 [首次使用](getting-started.md)准备 Reader，并让 `doctor` 通过。

## 连接现有 Reader

在本机创建一个 DSH patch 文件。下面路径是示例，请替换为你的 Reader 安装目录；三处目录需指向同一安装。

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

当前实测范围和保留项见 [DSH 验证记录](https://github.com/Kandecho/Video-Reader/blob/main/validation/dsh-integration-20261104/report-source.md)。该记录不代表 web/desktop GUI、全部模型或其它操作系统均已验证。
