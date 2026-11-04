# CLI 与 MCP 操作参考

本页供直接调用命令或工具时查阅。第一次安装和连接助手，请从[首次使用](getting-started.md)开始；模型、登录和文件位置见[安装与配置](installation.md)。完整导航见[文档首页](README.md)。

当前核心为 0.10.0rc6，生成的宿主接入文件版本为 0.5.5。

## 共享运行任务（0.10.0rc5）

普通 MCP 与 CLI 的 open/read/transcript 默认等 1 秒，未完成返回 job_id 与运行状态。
wait_seconds / CLI --wait 可设 0..30；不把长调用是否结束作为唯一进度反馈。
用 video_job(action="status", job_id=ID) 或 job status ID 查询；状态查询不取得材料锁。
用 action="result", wait_seconds=10，或 job result ID --wait 10，等待并取第一份材料页。
list / job list 查最近 20 项。新进程也能查询已有任务。

任务在组件独立 worker 内运行，不依赖调用方 CLI/MCP 的存活。
相同操作、来源、账号、配置和参数的活跃请求复用同一任务；不同参数独立，已完成请求不会永久遮蔽之后的材料修订。
stage、progress、stage_seconds 是实际阶段与阶段墙钟时间；它们不是 CPU 利用率或精确性能采样。
heartbeat_at / worker_alive 表示存活，progress_at 表示实际阶段或条目推进。
等待材料锁或账号锁分别显示 waiting_for_session_lock / waiting_for_account_lock。
尚未观察到启动的任务保留 unknown，不因等待时间推断已失败。
此前运行后失去 worker 所有权的任务报告 interrupted；失败保留 error 与任务 ID，不自动重启，也不恢复暂停的网络传输。

materials 只报告缓存可用性，不代表已交付或已观察。完成结果附 job 字段，正文与图片分页契约保持原样。
普通同步 Python Reader API 保持兼容；后台任务由新 job API 与宿主适配层提供。
CLI 需要对组件 cache、auth 状态目录有适当写权限。更新后重启已连接的 MCP，加载新工具与参数；旧进程不自动热更新。

## 0.10.0rc1 新增操作

[材料与续读](material-delivery.md)说明 adaptive / uniform / scene / dense、字节分页、稳定 cursor、原图与区域精读、增量 ASR、声音测量及显式修订导出。[安装说明](installation.md)说明可变根目录、可选模型和手动 YouTube Cookie；[批量队列](scroll-batch.md)属独立 Scroll。默认 16 个 Reader 工具和 3 个 Scroll 工具；本页旧章节中的历史数量不作为新接口清单。

## 搜索、热门与轻预览

没有视频链接时，Agent 可按主题调用 `video_search`，或用 `video_discover` 获取 B 站热门候选，选择后直接交给 `video_open`。复用组件自己的独立登录，不要求用户找链接。热门来自平台公共热门列表；基础版本尚未学习用户偏好。

```powershell
& 'D:\IA\apps\video-reader\run.ps1' search '科普 错觉' --page-size 20 --min-duration 90 --max-duration 360
& 'D:\IA\apps\video-reader\run.ps1' search '科普 错觉' --page 2 --order newest
& 'D:\IA\apps\video-reader\run.ps1' discover --page-size 20 --max-duration 600
```

返回标题、简介、UP 主、时长秒数、发布时间、播放量、BV 和规范 P1 链接。搜索支持 `relevance/views/newest` 排序；CLI 用 `--order`。`page_size` 为每个平台页请求的数量（1–50），`page` 从 1 开始。时长筛选在本页结果上执行，所以返回数量可少于 page_size，甚至为空；只要 `next_page` 存在，仍可继续翻页。

默认排除本组件已有任一分 P 会话缓存的 BV，可用 CLI `--include-cached` 或 MCP `exclude_cached=false` 包含它们。`cached` 只表示已有来源缓存，不等于完整阅读或校对。搜索/热门只取候选元数据，不下载视频、不把简介当作已看内容；真正阅读继续完成全片语音、画面分页和校对。请求失败如实报错，不伪装成“没有结果”。搜索使用平台设备标识和 WBI 签名，临时 Cookie 快照会清理，不修改浏览器会话。

`video_preview(source, offline=False, include_comments=False, density='light', max_frames=None, contact_sheet=False)` 返回时间轴图片与字幕等材料，优先复用完整缓存，否则使用原生分镜。默认 light 为 5 张；密集和批量参数见[材料接口说明](material-reference.md)。缺字幕或缩略图保留为缺项；预览不等于读完。共享缓存与取数设置在 `preview.*`，个人首页流、记忆和投递由 Scroll 编排。

## 完整语音与基础校验

`transcript` 不指定区间时请求全长；CLI/MCP 每次默认处理一个缺失块并返回已就绪材料与 remaining_ranges，继续调用补齐；`--complete-range` 保留整段阻塞方式，Python 旧调用默认行为保留。默认 `--source auto` 优先已有字幕。`--source asr` 可在已有 CC / AI 字幕时独立转写音轨，保留两份来源。`--source captions` 只读字幕，不暗中转写。整段按 120 秒提交进度，带两侧 2 秒解码上下文，按词时间中点分配区间归属。中断后仅补未完成区间。模型、设备、语言、提示上下文或解码版本不同，缓存不会混用。

```powershell
& 'D:\IA\apps\video-reader\run.ps1' transcript 'v_会话ID' --source asr
& 'D:\IA\apps\video-reader\run.ps1' transcript 'v_会话ID' --source asr --offset 60
& 'D:\IA\apps\video-reader\run.ps1' transcript 'v_会话ID' --source asr --no-verify
```

`coverage.complete` 表示指定音轨区间已处理，`missing_ranges` 给出缺口；它不表示所有页已被 Agent 阅读，也不表示识别正确。静音处理完成后无需重跑。ASR 保留解码与低置信词信息；概率并非事实正确率。`--context` 可提供不超过 1000 字符的术语提示，默认只用本视频标题。

AI 字幕和 ASR 在未校对时默认用本地 OCR 比对当前返回页；已校对及定点返读的规则见“返读来源一致与按需 OCR”一节。两帧中近乎相同的整行文案可标出差异；`--view evidence` 展开独立的 `screen_candidate`、`raw_text` 和时间戳证据，默认正文只保留疑点标记。OCR 不覆盖原始记录；后续宿主校对单独保存。整片实测发现高置信且稳定的 OCR 仍可能漏字、错字，因此不能自动覆盖语音文字。`not_corroborated` 不等于已核准。宿主应查看重要冲突后形成回答。CC 默认不比对，可用 `--verify` 显式检查；`--no-verify` 跳过比对。

`read` 默认启用本地 OCR。大号数值或公式会以 2 帧/秒向后观察最多 10 秒，区分变化、局部稳定和未解决状态。普通抽帧可选用观察到稳定的后续画面，返回真实时间戳及原始帧路径；`--timestamps` 保留指定时刻的像素，另附 `temporal.stable_reference`。MCP 同时传递参考图片。`--no-temporal` 关闭本次分析。配置项是 `vision.enabled`、`vision.lookahead_seconds`、`asr.chunk_seconds`。

目前只追踪 OCR 可识别的大号数值和公式，不是通用动画结束检测。停留一秒不证明语义已结束；公式会继续检查整个局部窗口。窗口末尾仍变化或字段消失会保留未解决信息。长句对齐、没有烧录字幕、低清或花字仍可能无法自动纠错。不能将这些基础缺口仅归因于阅读策略。

完整阅读和局部核对按[宿主操作契约](../skill/SKILL.md)执行。

## 忠实校对与按需披露

语义校对由宿主 Agent 结合所处理范围及必要上下文完成，再用 `video_review` 保存校对稿。不额外要求云服务或笔记步骤。组件本身不内置另一个语言模型；现行 `skill/SKILL.md` / MCP instructions 要求宿主承担首次校对，尚未校对的文本明确标为 `pending`。调用普通 Python API 而不执行宿主校对流程，不会凭空生成校对稿。

默认 `transcript` 和 `read.speech` 只返回正文、时间、段落 ID、校对状态和必要疑点标记。已有校对稿优先使用校对文本；按需指定区间和 `--view evidence` 才展开原文、逐项修改及理由、原始词级时间/概率、OCR 对照和复听引用。`--view raw` 选择原文字面。证据仍不能解决问题时，继续取帧或 `relisten`；这减少后续返读和上下文输入，但不消除首次准备成本。必要语境不能省略；新体验是否需要先校对整个回答范围，属于下一步流程调整，不由 `review.complete` 自动决定。

```powershell
& 'D:\IA\apps\video-reader\run.ps1' review prepare 'v_会话ID' --source asr
& 'D:\IA\apps\video-reader\run.ps1' review commit 'v_会话ID' --source asr --payload 'D:\path\review.json'
& 'D:\IA\apps\video-reader\run.ps1' transcript 'v_会话ID' --start 160 --end 188 --view evidence --source asr
& 'D:\IA\apps\video-reader\run.ps1' relisten 'v_会话ID' --start 161 --end 188 --term '主体'
```

`prepare` 可带 `--start/--end`，已处理完该区间即可校对，不要求先转写全片。读取每页和必要上下文后，将返回的 `review_scope` 原样复制进 commit payload；提交可据此确定范围。`scope_review.complete` 仅表示区间审阅完成，`review.complete` 仍表示全片。补读其他区间保留已存校对，新段落或原文变化的段落仍待审；区间材料变化会拒绝旧提交。省略范围保持原有全片契约。

`prepare` 返回 `snapshot_id`、`base_revision` 和分页段落；`commit` 保存最小文字差异、证据及已审阅 ID，包含无需修改的段落。完整 payload 见 `skill/SKILL.md`。语境、标题、同一会话的实际返回帧、带来源术语和已完成复听均可引用。字幕与独立 ASR 分别校对，不混用缓存；术语仅属于本片。`issues` 可记录未解决项，默认正文保留 `review_uncertain`；空 note 可撤销疑点。原文相同的 correction 可撤销先前修改。每次提交保留历史，旧 revision/snapshot 会被拒绝。

原始字幕、ASR 不覆盖。全部 Whisper 词时间和概率保存在会话里，`words` 始终对齐 `raw_text`；校对字词沿用原段落的起止时间，不伪称重新字级对齐。校对完成度、语音处理覆盖度与准确性分别报告。校对不是摘要，不能删句、改写作者观点或按全局同音字表替换。

`relisten` 真正启动本地独立进程重新识别，最多 60 秒源音频，默认 60 秒运行限额（可设 1–180 秒）。默认只读精确请求音频，保留分段时间、关闭词级对齐和短片 VAD，单温度解码且限制新 token；`--precise-words` 使用词级时间与两侧上下文。超时会终止进程树并记录 `timed_out`，失败不会自动调用云端。每次结果与参数保存到 `data/cache/<session>/relistens/<job>/`，不覆盖基线。结果明确为未核实候选，并与原始基线对照，对显著变短/重复做提示；复听完成也不保证听对。短窗仍可能漏句或重复，应扩大语境、查看原片或保留未解决项。中断由当前调用进程处理，无新增常驻服务。

复听默认不注入视频标题：实测标题会压过短语音并反复混入结果。需要时由宿主显式提供少量已核实的 context/terms。0.10.0rc2 起，新 Whisper 转写也不再自动注入标题。中文标题导致英文讲解漏句的同音频对照已复现；显式 context 仍可使用，分段策略保持。旧缓存和校对保留：尚无无提示轨时默认复用旧轨；新的默认解码另存无提示轨。用 context 空串显式选新轨，或显式传原标题/分 P 标题重开旧轨。

校对稿和修改历史在 `data/cache/<session>/reviews/<snapshot>.json`。默认正文不重复携带这些证据，原始 manifest 仍保留。0.5 以前的 ASR 记录因解码版本变化可能需重新识别；原始记录仍保留。

## 返读来源一致与按需 OCR

`read` / `video_read` 现在与 `transcript` 一样接受 `source`、`context`、`view` 和 `verify`。已选择独立 ASR 时，返读画面继续传 `source=asr`，就能保持同一份校对稿和证据；`auto` 仍优先平台字幕。`read` 不会启动新转写。

```powershell
& 'D:\IA\apps\video-reader\run.ps1' read 'v_会话ID' --start 16 --end 29 --timestamps '20' --source asr --no-temporal
& 'D:\IA\apps\video-reader\run.ps1' read 'v_会话ID' --start 16 --end 29 --timestamps '20' --source asr --view evidence --no-temporal
& 'D:\IA\apps\video-reader\run.ps1' read 'v_会话ID' --timestamps '270.8' --source asr --no-verify --no-temporal
```

自动语音 OCR 的新规则：未校对的普通机器语音页仍计算缺少的核对；已校对的 reading/raw 正文只复用已有核对。显式时间戳取帧默认也只复用已有语音核对，不再顺带新扫整页语音。`verify=true` 或 `view=evidence` 可补算当前页缺少的机器语音核对，已有缓存继续复用。`verify=false` 则不调用语音 OCR。CC 仍需 `verify=true` 才开始核对，`vision.enabled=false` 仍关闭核对。

返回的 `screen_verification`（`read` 内在 `speech` 下）说明策略及 computed/cached/skipped 段数。跳过不是通过，也不会将 pending 改成已校对；已有冲突和未解决疑点继续可见。请求原文、证据或修改来源时仍使用同一 source/context。`timestamps` 只选择画面，随附语音仍由 start/end 和分页决定；需要局部语音时显式限制区间。

`verify` 控制语音与屏幕文字核对，`temporal` 单独控制数值/公式画面的 OCR 观察。需要关闭两种分析时同时传 `--no-verify --no-temporal`。工具名不变，已连接的 MCP 宿主需重新启动服务以刷新参数定义。

## 可选 Qwen

日常 `transcript` / `read` / `review` 及对应 MCP 工具支持显式 `source=qwen`。它使用组件内已有 Qwen3-ASR-0.6B 和 ForcedAligner，当前配置针对中文、Windows CUDA GPU。`auto` 仍优先字幕、无字幕用 Whisper；`source=asr` 仍明确表示 Whisper。未修改用户 config.json，也不自动换引擎、下载模型或启用云端。

```powershell
& 'D:\IA\apps\video-reader\run.ps1' transcript 'v_会话ID' --source qwen
& 'D:\IA\apps\video-reader\run.ps1' read 'v_会话ID' --start 16 --end 29 --timestamps '20' --source qwen --no-temporal
& 'D:\IA\apps\video-reader\run.ps1' review prepare 'v_会话ID' --source qwen
```

三种调用须保持同一 source/context。Qwen 不自动注入标题，显式 context 才提供提示。其原文、profile、时间和校对快照独立保存；原有字幕、Whisper 和校对记录不覆盖。普通 reading 仍是精简正文；evidence 展开原始字/词级估计时间。概率不可用时返回 null，不伪造置信度。read 只读缓存，不启动转写；video_relisten 仍使用独立 Whisper 短窗候选。

每个至多 60 秒的源区间带两侧 2 秒上下文，由独立进程解码和对齐。每完成一段即落盘，中断后只补缺段。每个 worker 默认限时 300 秒，超时终止其进程树，不自动回退。新安装 qwen.runtime_dir 默认 runtimes/qwen；本机未显式指定时继续使用既有 research/asr-engine-20261021/.venv，保留原 profile。这个环境仍是本机可选功能的运行依赖，不能删除。qwen.model_path、aligner_path、runtime_dir 均可配置，安装方式见 installation.md。doctor 的 qwen_assets_present 只检查本地资产，不冒充 CUDA 运行测试。

模型时间不是人工真值；80ms 是时间分类步长，不是精度承诺。接缝分歧和零时长单元保留告警，词时始终描述原文，不自动重对齐校对文字。每段重新加载模型有额外开销；本次不引入常驻 GPU 服务。

用户确认对齐成熟阅读工具的**能力范围**：可靠转写、相关画面、时间引用、局部补看和疑点留痕。不是已经证明与某项目同等准确。连续动作、音乐/音效/语气理解、大规模人工盲稿及逐字毫秒级标注不作当前交付门槛。日常任务真的被这些缺口阻断时，再评估投入。当前默认 Reader 为十六工具，列表见 MCP 一节；更新后宿主需重启服务以刷新说明。接入验收见 [0.6.2 记录](../validation/qwen-0.6.2/report-source.md)。

## 作品列表与独立预览

Reader 新增 `video_uploader_videos` 与 `video_preview_batch`；原有 `video_preview` 追加可选的 density/max_frames/contact_sheet 参数。CLI 的 `uploader-videos`、`preview`、`preview-batch` 直接调用 Reader，不初始化 Scroll。默认 Reader 16 工具、Scroll 3 工具；既有读取、转写、校对、复听签名保持兼容。参数、完整性字段和密集分镜策略详见[材料接口说明](material-reference.md)。

## 独立目录与公共依赖

本目录包含：

```text
video_reader/                 通用读取实现，含内嵌抽帧组件
scroll_agent/                 个人工作流，复用 Reader
skill/、scroll-skill/          两个宿主流程的源稿
integrations/                 由构建脚本生成的薄插件
.venv/                        本组件自己的 Python 包环境
models/faster-whisper-medium/ 独立模型副本与来源校验
config.json                   相对路径配置，默认 local，Gemini 关闭
data/cache/                   Reader 媒体与校对会话
data/preview/                 共享轻材料
data/agent/                   Scroll 记忆、轮次和日记录
auth/bilibili/                本组件的扫码登录凭据、刷新凭据和临时二维码
examples/                     自制 12 秒视听样本
licenses/                     上游许可与已安装 Python 包的许可清单
docs/、planning/              路由、操作说明、当前路线
research/、validation/         调查和版本验收证据
run.ps1、launch_mcp.py         CLI 与 MCP 入口
```

**公共运行环境不自带**：Python 3.12（已测 3.12.13）、FFmpeg/ffprobe（已测 8.1.1）、Node（已测 24.15.0，YouTube JS 解算使用）。FFmpeg、ffprobe 和 Node 需在 PATH 中。PowerShell 7 用于便捷启动，uv 用于创建/重建 Python 环境；运行已安装组件不需要 uv。

Python 包和已验证版本在 `requirements-runtime-windows.txt`：包含 MCP 1.30.0、faster-whisper 1.2.1、PyAV 16.1.0、yt-dlp 2026.08.19、rapidocr-onnxruntime 1.4.4 等。已锁定 PyAV，避开之前实测的新版接口不兼容。OCR 的检测、识别和方向分类 ONNX 权重随组件自己环境内的包安装，运行时不联网下载。

组件不引用旧 Codex 工作区、watch 安装目录、BiliNote 源码或模型路径。Whisper medium 权重已复制到本目录，不是链接。模型 `model.bin` 的 SHA-256 已与 Systran 官方模型的 LFS 哈希比对一致，记录在 `models/faster-whisper-medium/model-provenance.json`。

首次安装或公共 Python 路径变化后，可运行：

```powershell
& 'D:\IA\apps\video-reader\bootstrap.ps1'
```

这会从公共 Python 创建本组件自己的 `.venv` 并安装所选依赖，不会下载模型。`-FullRuntime` 使用锁定依赖；`-Features mcp` 可跳过可选 OCR。若移动整个组件目录，应重建 `.venv` 并重新生成宿主的 MCP 路径。用户指定的外部视频、字幕或 Cookie 文件属于显式输入，不是组件内部项目依赖。

## MCP

CLI 与两个 MCP 在进程入口显式将标准输入、输出和错误流设为 UTF-8，复用同一个配置函数。不要依赖 `PYTHONIOENCODING`：当前 `-I` 启动会忽略 `PYTHON*` 环境变量。修复覆盖转写日志中的中文和连接号，避免宿主按 UTF-8 读取 GBK 后关闭日志管道。已运行的旧 MCP 需重连才能加载；不改变 Windows 全局编码。见 [UTF-8 修复验收](../validation/utf8-20261027/report.txt)。

`mcp-config.json` 含当前安装路径的启动配置，交给其他宿主接入即可。默认 20 工具：`video_job`、`video_search`、`video_discover`、`video_uploader_videos`、`video_preview`、`video_preview_batch`、`video_open`、`video_read`、`video_transcript`、`video_review`、`video_relisten`、`bilibili_login`、`video_continue`、`video_frame`、`video_sound`、`video_export`、`video_youtube_status`、`video_comments`、`video_danmaku`、`video_tasks`。通用任务见[任务参考](tasks.md)。评论、楼中楼和弹幕分页见[材料参考](material-reference.md)。更新工具列表后，需要重启已连接的 MCP 进程。

## Codex / Claude Code 薄插件 0.5.5

共享核心版本为 0.10.0rc6，生成适配器版本为 0.5.5。插件仅含清单、双 MCP 启动配置、两个分工明确的 Skill 和短说明，每端 5 文件。源码、`.venv`、Qwen 环境、模型、凭据和缓存仍在安装目录，不复制进插件。共用磁盘数据，不是共用单个内存进程；Qwen 仍错峰使用。

包名保留 `video-reader@video-reader-local`，包含 `video-reader` / `scroll-agent` 两个独立 MCP。两个 Skill 分别为 `$video-reader:video-read` 与 `$video-reader:scroll-agent`；自然语言也可自动路由。生成成功不表示某个宿主已经安装或启用；以宿主查询结果为准。更新后重新连接 MCP 才加载新的工具表，日推脚本不依赖这个会话。

```powershell
codex plugin marketplace add 'D:\IA\apps\video-reader\integrations\codex'
codex plugin add 'video-reader@video-reader-local'
codex plugin list --marketplace 'video-reader-local' --json
```

Claude Code 使用同一生成器和共享核心；标准安装命令如下。0.5.1 安装、参数与新进程实测见 [rc2 验收](../validation/reader-0.10.0rc2/report-source.md)，此前原生图片和宿主任务见 [rc1 验收](../validation/reader-0.10.0rc1/report-source.md)，不要将包格式校验代替实际安装。更新后既有会话可继续完成工作，新会话重新加载 MCP 与 Skill。

```powershell
claude plugin marketplace add 'D:\IA\apps\video-reader\integrations\claude'
claude plugin install 'video-reader@video-reader-local' --scope user
```

显式技能入口为 `/video-reader:video-read`。本轮没有准备公共商店发布材料。

`skill/SKILL.md` 是唯一阅读流程源稿，`scroll-skill/SKILL.md` 是个人工作流源稿。`tools/build_plugins.py` 将它同步到两个包，并把 CLI 回退位置改为共享核心的绝对路径，不从插件缓存推算核心位置。两端清单和目录规则分别适配；源码生成目录在 `integrations/codex` 和 `integrations/claude`。

```powershell
& 'D:\IA\apps\video-reader\.venv\Scripts\python.exe' 'D:\IA\apps\video-reader\tools\build_plugins.py'
```

若移动核心，先重建 `.venv`，重新生成包，再更新宿主安装。若修改 Skill 或插件绑定，更新构建脚本中的插件版本、生成并重新安装，不直接改宿主缓存。由手动 MCP 切换为插件时应去除重复注册；卸载薄插件不删除 D 盘核心和业务数据。

Codex 插件调用超时为 3600 秒，Claude 为 3600000 毫秒；不是 Qwen 每段的 worker 限时。0.2.0 的新工具与共享路径验收见 [0.7.0 记录](../validation/agent-0.7.0/report-source.md)；此前八工具的 115 项基线保留在 [0.1.0 历史验收](../validation/plugins-0.1.0/report-source.md)。

## 平台配置与云端选项

`config.json` 的路径均相对该配置文件。Bilibili、YouTube 与通用 yt-dlp 来源可在 `platforms` 下分别配置清晰度、字幕语言和显式 Cookie 文件。裸 BV 默认 P1，带 `p` 的链接使用正确分 P 与 CID，超出范围会报错。

默认使用组件自己的 B 站 Web 扫码会话。二维码在本机生成，不发送到二维码转换网站。用户用目标账号的 B 站 App 扫码后，登录 Cookie 和刷新凭据保存在 `auth/bilibili/credential.json`；`cookies.txt` 为 yt-dlp 兼容副本。`auth/` 已加入 Git 忽略。文件含登录凭据，应只在本机由本用户使用；工具结果和普通日志不返回这些内容。

```powershell
& 'D:\IA\apps\video-reader\run.ps1' login start
# Agent 打开返回的 qr_image_path，用户扫码并确认后：
& 'D:\IA\apps\video-reader\run.ps1' login poll 'login_返回的ID' --wait 20
& 'D:\IA\apps\video-reader\run.ps1' login status
& 'D:\IA\apps\video-reader\run.ps1' login refresh
& 'D:\IA\apps\video-reader\run.ps1' login logout
```

Agent 负责这些调用，日常使用不要求用户运行命令或导出 Cookie。MCP 的 `bilibili_login(action="start")` 直接返回二维码图片，`poll` 用不透明的 `login_id` 继续查询。登录过程中若后续验证暂时断网，已确认的二维码响应仍会保留，可继续 poll，不需要重新消费二维码密钥。

`status` 与每次在线 `open` 都会实时核验登录身份；网络不可用返回 `authenticated=null`，不会删除凭据或冒称已退出。每次使用时，若距离上次成功续期检查已满 24 小时，会检查平台是否要求刷新；`refresh` 可立即触发检查，不强制轮换平台认为仍有效的凭据。平台要求刷新时，组件保存新 Cookie 和新刷新凭据，再确认旧凭据的更新；确认暂时失败会在下次使用时重试。组件无需为续期常驻运行。

视频下载和字幕读取使用同一份凭据快照。yt-dlp 可改写该临时副本，处理结束后副本会删除，不会污染组件保存的正式凭据。账号更换后创建新的会话缓存范围，同一账号正常续期继续复用原缓存。查看已有会话的 `read` 和 `transcript` 不要求联网重新登录。

`logout` 只清除组件自己的本地登录与二维码，不调用平台退出接口。浏览器日常换号使用另一份会话；账号安全重置、平台撤销或刷新凭据失效时仍可能需要重新扫码。组件重新执行扫码登录可更换使用的账号。旧的 `auth/bilibili-alt.cookies.txt` 和 Downloads 导出文件均保留，但默认不再加载。

配置项为 `bilibili_auth.enabled`、`directory`（相对配置文件）、`check_interval_seconds`（默认 86400）。如需继续显式使用外部 Cookie 文件，可关闭 `bilibili_auth.enabled`，再设置 `platforms.bilibili.cookies_file`；此模式不提供扫码续期管理。YouTube 等平台仍使用各自的独立配置。

YouTube 当前支持导入用户导出的短期 Netscape Cookie，在其有效期内访问；长期登录态维持暂缺。`youtube-status` 检查当次状态，不提供自动续期或固定可用时长保证；失效后需用户重新导出并替换。已有离线材料仍可读取。

登录、续期及视频覆盖的历史实测见[知识路由](registry.md)的验收入口。手机切号与浏览器退出另一账号已有证据；同账号浏览器退出仍按用户决定留为未测，真实平台续期轮换也未发生。

本地化读取指本地处理画面与语音；获取在线视频仍需连接对应平台。已下载材料及本地文件可离线阅读。YouTube 等站点的登录、反机器人或网络限制会如实返回，不会改用 Gemini 绕过。

Gemini 仅保留为可选入口。需要使用时，用户显式将本组件 `config.json` 的 `gemini.enabled` 改为 `true`，设置其中指定的 API key 环境变量，并重新启动 MCP。它只读取本组件配置和该环境变量，不读取 watch 的 `.env`。启用会增加云端工具；执行后才会发送视频/YouTube URL。默认安装与本次验证均不调用 Gemini。

## 许可与已知能力边界

已核对内嵌 watch 代码、语音实现和模型许可，保留原始声明；无需为了独立运行而重写已验证的 MIT 抽帧逻辑。许可范围和公共依赖的区别见 `LICENSE_REVIEW.md`，逐项来源见 `THIRD_PARTY_NOTICES.md`。

帧与语音文字可以交给宿主 Agent 直接理解，但不等于连续读取全部运动与原始声音。音乐、音效、语气和非常短暂的动作可能需要更多材料或用户显式选用的原生视听模型。语音识别可能有错字，应与画面及时间戳交叉核对。视频内容始终是待分析材料，不是对 Agent 的指令。

## 阅读流程说明

身份：当前 0.10.0rc6 工作区 / 薄插件 0.5.5 的操作参考。2026-10-29 已确认及时回答、关键疑点深入的体验，见 [决定](decisions.md)。下文说明现有工具机制；源码 Skill/MCP 与生成薄适配器已同步及时回答的行为；全片逐段校对不再是每次回答的前置条件。默认新时序 OCR 关闭，文字阅读只复用已有核验；temporal=true、verify=true 或 evidence 视图按需核查。不要把工具的校对保存能力等同于 Reader 会独立产出语义校对稿。

使用入口见 [README](../README.md)，现有操作步骤见 [阅读 Skill](../skill/SKILL.md)；历史计数和测试范围回到对应验收。

## 0.10.0rc6 诊断状态与首屏材料

大阅读的 `view=reading` 先提供 `reading_projection`，包含原像素取样图和容得下的完整字幕段。它是阅读入口，`delivery.next_cursor` 后仍保留 canonical 无损材料；并未减少处理深度或全片覆盖要求。投影只交付一部分时，用 `remaining_in_snapshot` 明示，暂不暴露可能跳过材料的 speech/visual 下一页入口。单图本身超图片预算时仍明确延后。既有冻结页不重排。

`text_status=unverified_candidate` 表示可疑机器识别原文；`recognition_assessment` 与 source_processed 处理覆盖分开。Qwen 的 `alignment_unresolved` / `unplaced_candidates` 保留 raw_text、input_range、owner_range、raw_alignment，不制造归属时间；该状态不等于声学无人声，尚存候选时 review.complete 为 false。处理过的旧缓存直接派生这些字段，原 profile、段 ID 与校对历史不变。新动态游标绑定诊断变化，旧冻结页仍可读。

元数据获取新增 extracting_source_metadata / retrying_source_metadata 阶段，仅明确网页瞬时超时或断连恢复一次；限制、预算耗尽和暂停不自动恢复。最终 AcquisitionError / job.error.details 保留 stage 与 attempts，成功也保留 acquisition.metadata_extraction 的恢复记录。下载前重新核对 B 站 part/CID。预览会在缓存写入前检查索引与图格，在线旁路旧坏缓存并至多一次有界重取；离线保留缺口。

Windows 状态读写共享 job 的短时 .status.lock，包括启动失败兜底，避免读 JSON 与原子替换交错。它不持有视频材料锁。详见 [修复验收](../validation/diagnosis-repairs-20261031/report-source.md)。续期不在本轮验证范围。
