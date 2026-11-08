# Video Reader 完整架构审计

冻结日期：2026-11-08。下文描述修复前状态；[后续修复结果](../architecture-fixes-20261108/README.md)另行维护。源码链接固定到[修复前提交 `13565e8`](https://github.com/Kandecho/Video-Reader/tree/13565e85a64e8fb8e9495262daa9b983e7ffbe69)，避免当前代码变化覆盖问题依据。

**建议保留 Reader、通用任务和 Scroll 三个职责域，修正模块之间直接依赖内部数据和规则的地方。** 这次补查没有发现必须重划三个职责域才能解决的问题。

目前较突出的耦合有三类：同一条规则由几处分别执行；一个模块读取另一个模块的内部记录；缓存结果没有准确区分所依赖的输入和本次请求。它们会让能力升级牵动原本无关的代码，也已造成几处可明确定位的行为问题。

本报告合并首轮审计与一次补查。首轮证据直接复用；补查覆盖平台获取、媒体处理、推荐、记忆和投递。ASR、OCR 只是其中两个例子。

## A 判断模块边界的依据

这里的高内聚，是让共同完成一项职责、需要一起变化的代码放在一起。低耦合，是让其他模块通过明确的输入、结果和状态使用这项能力，无需了解它内部如何实现。

例如，更换下载器应主要修改获取适配；调整推荐模型应主要修改推荐评估；扩充导出格式应主要修改导出。增加用户可见选项，需要入口和文档同步；改变材料含义、账号范围或发送规则，也可能需要调整相应接口。这些是有理由的共同变化。

本次以[有效决定](../../docs/decisions.md)、[当前架构](../../docs/architecture.md)和[已登记方向](../../planning/roadmap-20261021-source.md)为依据。重点保留通用读取、按需补看、原文与修订、账号隔离、可恢复任务及授权发送。

| 能力 | 变化应主要发生在哪里 | 当前判断 |
|---|---|---|
| 平台搜索、获取、账号适配 | Reader 的来源、平台和认证模块 | 获取适配已有基础；业务联网规则与账号表示仍有外泄 |
| 字幕、评论、弹幕 | 平台材料翻译及各自覆盖处理 | 原始协议有重复解析，应局部复用 |
| 解码、取帧、选帧 | 解码适配、选帧策略与材料身份 | 解码边界可保留；选帧缓存缺少实际依赖的输入 |
| 语音、画面文字、音频分析 | 各能力实现、结果与诊断 | 识别细节和缓存版本需收口；音频缓存混入请求状态 |
| 材料目录、分页、修订、导出 | Reader 的材料及证据接口 | 保全机制可保留；重复图像交付和跨域读取内部记录需调整 |
| 队列、分流、批读、任务消费 | reading_tasks | 独立任务职责成立；调度与消费之间仍共享内部载荷 |
| 推荐、个人记忆、日轮、投递 | Scroll 内各自职责模块 | 推荐评估与发送账本可保留；缓存查找和记忆入口有多余依赖 |
| 宿主调用、作业、运行控制 | 各执行模块及装配入口 | 共用执行基础可保留；配置一致性与错误分类需补齐 |
| CLI、MCP、插件、发布 | 入口适配与构建 | 共核心成立；候选包漏入口，个别测试会写正式适配器 |

## B 平台获取应共用规则，保留各自材料语义

### 搜索绕过了统一联网管控

公开搜索和热门发现创建 BiliSession 后直接请求网络。预览候选走 Platform，受暂停、每日预算、请求间隔和响应大小约束。两条路径对同一类业务取数执行不同规则：平台暂停或预算耗尽后，搜索路径仍能发出请求。

应让搜索的业务请求遵守同一套受控请求规则，发现模块继续负责参数、签名、候选和分页。受控传输应接受现有认证上下文，保留匿名和已有 Cookie 路径；不能直接换成目前要求托管登录的 Platform，新增登录前提。认证本身的登录与刷新协议仍归认证模块。下载子进程与 Platform 也分别维护了相近的预算和暂停判断；共享状态和锁有必要，规则应由一处负责。

依据：[discovery.py:118](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/discovery.py#L118)、[BiliSession.request](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/bilibili_auth.py#L138)、[预览候选](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/preview.py#L17)、[Platform 管控](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/platform.py#L149)、[下载预算](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/acquisition_budget.py#L17)。这是补查的源码结论，未执行联网复现。

### 调用者仍了解凭据内部格式

Platform 直接调用认证模块的私有加载方法并读取 cookies 和 account_marker。材料目录知道 B 站 credential.json 的位置与字段，也自己计算 YouTube Cookie 身份。即使账号隔离规则不变，只改凭据存储或身份算法，也会牵动平台、发现和目录。

认证模块应提供公开的账号标识与请求上下文。目录只需要可离线取得的账号标识，业务传输需要经过认证适配的请求上下文。保留现有账号隔离和临时 Cookie 快照，不必增加通用认证框架。

依据：[platform.py:50](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/platform.py#L50)、[catalog.py:9](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/catalog.py#L9)、[youtube_auth.py:28](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/youtube_auth.py#L28)、[discovery.py:118](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/discovery.py#L118)。

### 部分平台协议被重复解释

community 和 aligned_danmaku 都解析弹幕分段接口的 protobuf 字段。完整获取和轻预览都解析字幕接口、选择轨道并翻译原始字幕。预览热评也单独绑定评论接口。平台字段或轨道选择规则变化时，需要同时修改几处。

应复用已有重复的协议翻译，例如分 P 元数据、字幕轨道与标准段、弹幕分段信息。预览继续决定轻量展示；完整获取继续负责媒体和完整材料；弹幕关联继续负责区间、来源绑定、覆盖与时间关系。它们不需要共用一个包罗所有用途的大返回对象。

依据：[community.py:251](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/community.py#L251)、[aligned_danmaku.py:65](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/aligned_danmaku.py#L65)、[sources.py:254](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/sources.py#L254)、[preview.py:207](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/preview.py#L207)、[preview.py:238](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/preview.py#L238)。

### 下载适配的现有边界可以保留

下载命令集中在 sources，yt-dlp 的计数适配留在独立 worker；上传者列表的提取器适配也集中在局部函数。更换下载实现会涉及这些适配点，这是合理范围。保持媒体位置、来源及分 P 身份、字幕、失败和覆盖结果后，任务与推荐模块无需了解下载器细节。

纯身份解析与受控短链展开也值得保留。没有依据为了增加平台或更换下载器，先建设全局插件注册系统。

依据：[sources.py:133](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/sources.py#L133)、[downloader_worker.py:12](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/downloader_worker.py#L12)、[uploader.py:39](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/uploader.py#L39)、[短链解析](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/sources.py#L42)。

## C 媒体能力升级需要准确的结果身份

### 音频缓存带入了上次请求的续读状态

音量测量每次最多处理 600 秒，缓存按实际处理区间保存，却把本次请求决定的 next_start 一起缓存。对于带音轨、时长至少 1200 秒的视频，先请求 0–600 秒，再请求 0–1200 秒，两次实际处理区间相同。第二次会复用前次的 next_start=None，失去后续读取提示；反序则让短请求带上多余续点。

应只缓存测量结果，在返回时按本次请求生成范围和续点。问题可以在 audio 模块内修正，无需改变任务或调度。

依据：[audio.py:11](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/audio.py#L11)、[缓存命中](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/audio.py#L16)、[续点生成](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/audio.py#L40)。这是确定调用条件下的源码推导，未补跑测量实验。

### 派生缓存没有完整绑定自己的输入

adaptive 选帧会使用原始语音片段确定部分取样点，但 read ID 没有包含这些输入或选帧政策版本。语音从未就绪变为就绪，或换 source、context 后实际语音片段改变，同窗口仍可能复用旧选帧。这里不使用宿主校对后的文字，不能因此要求每次校对都使选帧失效。

同类问题也出现在识别升级：Whisper 和 Qwen 主要用模型路径、配置和手动 revision 区分结果；OCR 用图像文件状态和手动 revision。原路径覆写模型或运行时但未更新身份时，可能复用旧结果。换到新模型路径已有隔离作用。

应由每项能力记录真正影响输出的输入与政策版本。依赖语音的选帧绑定实际语音；精确时间补帧和 uniform 不因无关语音变化失效。ASR 换代创建新语音轨，OCR 换代更新派生证据，不因此让未变的原文及宿主校对失效。安装清单若用于模型身份，须随实际资产核验和更新。

依据：[read ID](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/reader.py#L418)、[adaptive 输入](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/reader.py#L438)、[observation.py:19](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/observation.py#L19)、[speech profile](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/speech.py#L15)、[Qwen profile](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/qwen.py#L27)、[OCR 缓存](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/vision.py#L25)。首轮已用内存复现确认旧 OCR 缓存可直接返回，见[既有证据](summary.json)。

### 识别后端细节还散在上层

Reader 直接了解 Qwen 的组装与分块、Whisper 的文件和包就绪条件；通用诊断也解析厂商结构。Reader、CLI、MCP 直接探测 RapidOCR 包。新增另一种实现时，只替换识别函数不足以完成接入。

能力模块应集中提供版本身份、可用状态、解码、组装和诊断。上层继续负责覆盖、保存、分页和校对。不同后端不能提供的词时间或概率，应明确缺失；原始生成、对齐和未定位候选继续保留。OCR 的置信阈值与 Windows 预热要求也归所属能力维护。

依据：[语音编排](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/reader.py#L525)、[分块](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/reader.py#L633)、[诊断](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/recognition.py#L13)、[OCR 探测](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/reader.py#L413)、[MCP 预热](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/mcp_server.py#L405)。

### 解码、复听和导出已有可用边界

帧解码已返回图片位置、实际源时间和索引，精确抽帧区分请求时间与实际时间。替换解码实现应局限于适配和这些语义的验证。平台原生预览与本地源帧精度不同，可以保留各自路径。

音频测量与语义理解分开，复听保留独立结果、不覆盖基线，这些职责应保留。新增声音事件识别可以作为材料能力扩充，不把 quiet 或进程成功解释成“已听懂”。

导出目前只有一种格式，证据准备与 HTML 呈现同处一个小模块，有共同用途。出现第二种格式时再分出稳定证据包与格式渲染。新格式可以增加入口参数，任务库、Inbox 和调度无需参与。

依据：[解码结果](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/vendor/frames.py#L144)、[精确时间](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/vendor/frames.py#L330)、[细节资产](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/frame_detail.py#L19)、[复听](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/relisten.py#L35)、[导出](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/export.py#L14)。

## D 材料、任务与执行状态应由所属模块解释

### 调度和任务仍读取其他模块的内部记录

Background 直接查询任务 run 表、解释 payload，并调用消费器的私有校验。消费器又了解 Reader 的 CID 字段、资产校验私有函数；Controls 扫描 Reader job 文件。材料布局、检查点或状态结构变化时，这些消费者都可能跟着修改。

应由消费器提供“当前运行、许可关联、能否恢复”等公开判断；Reader 提供绑定资产校验、局部补证和完整活跃作业查询。现有 job list 只取最近 20 项，不能直接替代活跃扫描。Scroll 保留定时触发和 Inbox 编排，同库事务继续保留。

Reader 到 Consumer 的反向接线目前用于复用现有 worker。以后增加业务作业时，可在组合入口接线；单凭静态依赖环，不足以要求重写执行器。

依据：[Background 查询](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/background.py#L83)、[恢复检查](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/background.py#L171)、[任务补证](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/reading_tasks/consume.py#L213)、[活跃 job 扫描](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/reading_tasks/control.py#L162)、[现有 job list](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/jobs.py#L210)、[反向接线](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/reader.py#L61)。

### 作业记录与实际执行可能使用不同配置

父进程用自身配置生成作业身份，worker 却按路径重读配置，执行前未核对两者。长驻 MCP 启动后或排队后修改配置，可能按 A 配置去重、按 B 配置执行。首轮内存复现中，指纹不匹配的作业仍执行并完成。

应在 worker 边界确认有效配置版本，变化时明确拒绝或使用已固定的执行配置。这个保证适用于所有受配置影响的能力，不只模型。

依据：[作业身份](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/jobs.py#L142)、[worker 重读](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/job_worker.py#L26)、[执行](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/jobs.py#L246)、[既有复现](summary.json)。

### 宿主错误应先翻译，再交给任务政策处理

共享宿主通路区分连接超时、传输错误和普通失败。消费器又通过错误文本识别额度不足，调度器再据类别决定短重试。宿主适配或文案变化会影响业务判断。

应由宿主通路统一输出稳定类别和详情，任务与调度执行已有的暂停、重试政策。保留平台错误与模型额度的区别，以及只对子进程继承代理、期限控制和结构化返回。

可选原生音视频云端路径目前独立启用，供应商协议集中在 cloud 与 Gemini 适配，未自动接入本地失败回退。替换该供应商时可以局部调整协议与会话适配；当前没有第二供应商需求，不必预建统一云端框架。

依据：[HostError](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/host_runtime.py#L40)、[额度文本判断](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/reading_tasks/consume.py#L371)、[短重试](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/background.py#L153)、[可选云端](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/cloud.py#L17)。

### 完整材料与本次图像附件需要区分

超大 reading 结果先交可读投影，后续完整证据页再次带相同图片。首轮复现已确认 2 张源图生成 4 个 MCP 图像块。

应在 delivery／MCP 的交付约定中标明本轮已经附带哪些资产，同时保留无损材料和显式补取。去重范围要能区分不同请求和聊天。该证据证明交付重复，不能换算为模型计费或主聊天重放次数。

依据：[可读投影](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/delivery.py#L89)、[完整页](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/delivery.py#L153)、[MCP 附图](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/mcp_content.py#L9)、[既有复现](summary.json)。

## E 推荐、记忆和投递可以各自演进

### 推荐器仍扫描 Reader 私有缓存

个人推荐准备时仍扫描 v_*/manifest.json，读取来源和账号字段。材料布局或身份表达升级，会牵动推荐器。当前架构文档称 Scroll 已改用公开材料查找，这条路径实际仍有遗漏。

应复用 Reader.materials，再经公开读取取得材料。保留账号过滤、缓存优先和不重复转写。此处无需修改推荐评估方式。

依据：[缓存扫描](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/agent.py#L122)、[实际调用](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/agent.py#L186)、[公开查找](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/video_reader/reader.py#L49)、[当前架构说明](../../docs/architecture.md)。

### 记忆接口依赖了整套推荐配置

MCP 的记忆操作经 Agent(Reader()).memory 取得 Memory；CLI 也先构造 Agent。Agent 会校验推荐、宿主、投递和日轮配置并构造 Platform。只想查记忆时，无关配置出错也会使入口失败。

Memory 本身已能独立工作。记忆入口应直接完成必要的账号和配置装配，保留账号隔离。推荐或发送能力升级，不应阻断本地记忆的查询与修改。

依据：[MCP 入口](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/mcp_server.py#L62)、[CLI 装配](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/cli.py#L60)、[Agent 校验](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/agent.py#L25)、[Memory](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/memory.py#L14)。这是调用链结论，未做故障注入。

### 推荐评估和发送账本值得保留

推荐提示和结构化判断集中在 host，Agent 可替换 evaluator，并自行核对候选、数量和证据。更换推荐模型或提示，保持现有决策约定即可。用户偏好、明确反馈和 Agent 观察继续分开；固定日试用首条规则独立保留。

推荐与任务汇报共用 send_message，先持久预留，再发送，记录接受、拒绝或不确定。中断后不盲目重发，这个流程有实际职责。B 站目的地址、长度限制和表单细节仍分散在 Scroll 内；真实增加第二渠道时，再集中到渠道适配，保留旧账本及其幂等关系。

任务分流和批读继续由 reading_tasks 负责，Scroll 的兼容包装无需复制实现。它们与个人推荐有不同目的，没有理由合成一个通用策略引擎。

依据：[推荐评估](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/agent.py#L352)、[决策校验](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/agent.py#L259)、[记忆来源类型](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/memory.py#L11)、[共用发送](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/delivery.py#L12)、[发送账本](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/memory.py#L168)、[报告发送](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/scroll_agent/reports.py#L57)、[任务分流](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/reading_tasks/triage.py#L173)。

## F 共用核心成立，发布与验证仍有缺口

薄插件引用同一个外部安装，模型、凭据和缓存没有复制进两套宿主插件。CLI／MCP 的必要参数同步属于入口维护，不要求复制业务实现。

当前源码候选自动收业务包、测试和文档，却未收入六个运行脚本：install_scroll_task、run_scroll_daily、manage_scroll_background、run_scroll_background、scheduled_task_action 和 run_scheduled_hidden。按当前源码制作完整新包前，应补齐支持能力所需入口，并验证引用是否完整。首轮已有静态选择复现；这不代表旧发布包已经发生同样故障。

另有一项策略一致性测试把真实项目根传给插件生成器，会写正式适配器。应改用临时核心，复制真实 Skill 作为输入。首轮验证已在审计 runner 内隔离该调用，没有修改现有测试源码。

依据：[薄插件](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/tools/build_plugins.py#L30)、[构建清单](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/tools/build_candidate.py#L10)、[遗漏脚本清单](summary.json)、[测试写入入口](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/tests/test_reading_tasks.py#L115)、[可复用临时夹具](https://github.com/Kandecho/Video-Reader/blob/13565e85a64e8fb8e9495262daa9b983e7ffbe69/tests/test_plugins.py#L14)。

## G 已登记方向的改动范围与建议次序

| 已登记方向 | 建议在哪一层推进 | 需要保住什么 |
|---|---|---|
| 分层提速、按任务选块 | Reader 区分文字导航与按需视觉准备；Consumer 调整任务选块和包大小 | 完整任务的必要覆盖、原文、检查点、唯一结果和可补看路径 |
| 视觉证据生命周期 | 复用共享宿主与任务编排，验证视觉短会话；先处理已确认的重复交付 | 原图可回取；观察者与请求可关联；实测总耗时、重试和输入成本 |
| 回答级溯源 | Reader 提供绑定材料，任务／宿主关联本次交付、观察和具体结论 | 来源、分 P、时间、修订与资产身份；材料存在不直接当作结论已证实 |
| 推荐与分流收益 | 保持推荐、明确反馈、任务要求各自语义，用真实结果比较 | 不把未回复或单例观察扩大为用户偏好；日试用仍遵守固定首条规则 |

当前 Consumer 先备齐语音，再固定每四个时间块读一包。这适用于当前完整笔记策略，尚不能代表按任务选块。替代策略可在消费器内验证，队列和恢复机制继续复用。

建议先修会影响现有行为的联网管控、音频续点和作业配置一致性，并处理已复现的重复图像交付。随后沿真实能力升级，收口账号表示、材料查找、任务状态和能力诊断；派生缓存绑定自己的实际输入与版本。发布缺项在下一包前处理，测试副作用在验证维护时消除。

无需为这轮审计先增加独立服务、消息总线、重型数据库或通用插件框架。已有同库事务、账号隔离、原文修订、执行恢复和发送不确定账本，继续承担明确职责。

## H 验证范围与公开证据

首轮检查覆盖 71 个业务包 Python 文件。基线验证为 415 项通过、2 项真实 stdio MCP 协议用例待验证；补查只追踪源码与实际调用者。后续修复的验证不回写本次历史结果。

[公开摘要](summary.json)保留结构数量、四个有限复现与基线测试范围。完整指纹、原始测试文本和冻结 ZIP 保留在本地，没有作为源码提交。冻结前源码可通过上述 Git 提交回查。
