---
title: Video Reader 架构审计
subtitle: 2026-11-08 · 当前工作树 · 高内聚低耦合与能力替换边界
template: doc
theme: inkread
lang: zh
---

**保留 Reader／通用任务／Scroll 三域，局部补齐能力和状态契约。没有发现需要整体重构的依据。** 同框架换权重并使用新模型路径，现状已能通过配置完成。新增识别框架、同路径更新模型和改变消费策略时，仍有实现细节越界。

审计得到 **8 组主要发现**。优先处理模型／缓存身份与作业执行配置的两处正确性风险；其余结合已登记方向逐项收口。报告给出建议，不表示已经实施或获准启动后续开发。

## A 审计依据与覆盖

治理依据来自本次用户要求、[有效决定](../../docs/decisions.md)、[当前架构](../../docs/architecture.md)与[当前路线](../../planning/roadmap-20261021-source.md)。沿用通用材料组件、本地默认、宿主负责理解、原文与修订保全、一个共享核心的决定。

采用本机个人版 `code-governance`，结合缺席比较、真实消费者和变化影响判断。技能已存在，无需下载。三个并行审查分别覆盖识别能力、任务与状态边界、接口与运行层；主审查覆盖依赖图、材料交付和路线映射。

| 范围 | 本轮覆盖 |
|---|---|
| 三个业务包 | 71 个 Python 文件，11,811 行；全部解析导入关系，重点追踪实际调用与状态链路 |
| 依赖结构 | 226 个唯一模块依赖；包括函数内延迟导入，不据此直接判定启动循环 |
| 运行与接入 | CLI、两套 MCP、worker、PowerShell 启动器、共享配置、薄插件与源码候选构建 |
| 已登记方向 | 分层提速、视觉证据生命周期、回答级溯源与按需补看 |
| 基线 | HEAD 为 `4a9f981`，结论针对含既有未提交变更的当前工作树，不代指发布包 |

源文件指纹、边界依赖和强连通分量见 structure-evidence.json（本地证据：`validation/architecture-audit-20261108/structure-evidence.json`）。全库依赖扫描不等于逐行语义证明；结论来自相关代码、调用者、测试和下述有限复现。

## B 现有分域值得保留

```flow TD
当前宿主 -> Reader: 直接读视频
当前宿主 -> 通用任务: 任务与结果
当前宿主 -> Scroll: 个人工作流
Scroll -> 通用任务: 收件入队与定时触发
通用任务 -> Reader: 材料与局部补证
Reader -> 识别能力: ASR与OCR
Reader -> 材料修订: 原文和证据
通用任务 -> 共享宿主通路: 阅读调用
Scroll -> 共享宿主通路: 推荐调用
```

图示职责主干；兼容入口和实际反向依赖另见 D。模块是否内聚，要看哪些变化应共同发生。目录大小、接口数量和只有一个实现，都不足以判定结构失当。

| 对象 | 判断与承重关系 |
|---|---|
| Reader | 保留材料获取、识别、来源、覆盖、修订及回查。把它移入任务或推荐模块，会损失直接读视频的通用入口 |
| reading_tasks | 保留中立队列、要求、分流、领取、检查点与结果。移回 Scroll 会重新绑定私信或个人推荐 |
| Scroll | 保留 Inbox 原文、个人偏好、日轮、授权投递和定时触发。不能从单次阅读要求推导长期偏好 |
| 共享 SQLite | 保留同库事务。原消息／游标／入队与结果／run／许可的原子关系有实际恢复职责，不宜为分层拆成跨库补偿 |
| 校对与覆盖 | 保留原文、来源轨、profile、局部校对和未核查路径。处理完成、交付、宿主观察与准确性继续分开 |
| worker 与锁 | 保留既有 job、状态短锁、媒体锁与细节资产锁。没有依据为能力升级重写执行器 |
| 薄插件与共享宿主 | 保留共核心、共模型与共缓存；传输处理和推荐／任务语义分开，不复制第二套阅读核心 |

依据：[Store](../../reading_tasks/store.py#L29)、[结果原子提交](../../reading_tasks/queue.py#L244)、[Inbox 事务](../../scroll_agent/inbox.py#L226)、[校对身份](../../video_reader/review.py#L12)、[细节帧回归](../../tests/test_architecture_repairs.py#L79)、[薄插件生成](../../tools/build_plugins.py#L30)。

## C 两个升级身份风险应先解决

### 01 模型与运行时身份没有完整进入派生缓存

Whisper profile 绑定模型路径、设备和解码配置。Qwen 绑定模型、对齐器和运行时路径。二者依靠手动 revision 区分实现版本，没有绑定实际模型资产版本。Whisper 进程内模型池也按路径、设备与精度复用。

OCR 原始缓存绑定图像大小、修改时间和 `FRAME_REVISION`；二次核验及 Reader 时序结果另有缓存键。只更换 OCR 实现而不改变相关身份，不能保证三层结果一起更新。

**真实触发条件是同路径替换权重或运行时、但没有改变 profile／revision。** 这时可能继续复用旧结果。换到新模型路径已有隔离作用，不能据此说现有模型配置机制完全不可用。本轮未发现真实用户材料已经因该条件误用缓存。

纯内存复现确认：相同图像 stat 和 revision 下，`ocr_frame` 返回旧缓存，新引擎未执行。证据：probe-evidence.json（本地证据：`validation/architecture-audit-20261108/probe-evidence.json`）。

最小建议：能力模块提供明确的 engine／model／policy 身份，将其传入所属派生缓存。模型版本可复用安装时清单；清单须经安装／启用时核验，并随实际资产同步更新，不必每次读取重新哈希大权重。ASR 换代创建新语音轨；OCR 换代更新派生证据身份，不因此使未变的语音原文及宿主校对失效。旧轨与旧证据继续可回查，进程内模型池也要遵守同一代际。

位置：[speech.py:15](../../video_reader/speech.py#L15)、[speech.py:52](../../video_reader/speech.py#L52)、[qwen.py:27](../../video_reader/qwen.py#L27)、[vision.py:25](../../video_reader/vision.py#L25)、[vision.py:189](../../video_reader/vision.py#L189)、[reader.py:418](../../video_reader/reader.py#L418)。已有 [Qwen 换策略保留旧校对测试](../../tests/test_qwen.py#L75)可作为保全行为的基础。

### 02 作业绑定配置没有约束 worker 实际执行配置

父进程按自身 `Reader.config` 生成 `config_identity`，随后只向 worker 传配置文件路径。worker 重读文件，仅核对缓存根目录。执行方法前没有检查配置身份是否仍匹配。

长驻 MCP 启动后修改配置，或作业排队后修改模型配置，可能出现“按 A 配置去重、按 B 配置执行”。纯内存复现得到：指纹不匹配，实际执行 model-B，最终仍是 completed。

最小建议：在 worker 边界核对有效配置代际。发生变化时明确拒绝并要求重载，或冻结执行所需配置。不能把只用于请求去重的身份当成执行保证。

位置：[jobs.py:142](../../video_reader/jobs.py#L142)、[jobs.py:160](../../video_reader/jobs.py#L160)、[job_worker.py:26](../../video_reader/job_worker.py#L26)、[jobs.py:246](../../video_reader/jobs.py#L246)、[MCP 长驻 Reader](../../video_reader/mcp_server.py#L70)。复现代码见 audit_probes.py（本地证据：`validation/architecture-audit-20261108/audit_probes.py`）。

## D 三处边界应按真实变化收口

### 03 ASR 和 OCR 的后端细节进入了消费者

Reader 掌握 Qwen 组装、`qwen_chunk`、60 秒分块、Whisper 文件与包的就绪规则；通用 recognition 也解析 Qwen 诊断。CLI 与任务模块重复维护 source 名单。增加异类 ASR 时，变化面超过 decoder 适配。

OCR 调用已集中在 `vision.ocr_frame`，输出 `text / confidence / box`，这是有效基础。但 Reader、CLI、MCP 仍直接识别 RapidOCR 包。只换识别函数，上层可能继续判断 OCR 不可用。现有置信阈值也不能直接假定适用于新模型。

最小建议：在 Reader 域内集中 `profile / available / decode / assemble / diagnostics`；OCR 另提供能力状态与所需 warmup。Reader 继续负责覆盖、持久保存、分页和校对。厂商原始输出留作证据，消费者读取归一化诊断。

Windows OCR 主线程预导入有既有死锁依据，应迁入能力初始化入口，不能直接删除。公开增加 source 选项时，入口文案更新属于必要变化；任务域自行维护厂商名单则可以收口。当前 Qwen 工具说明仍有两处旧的“Chinese”描述，宜随契约维护纠正。

位置：[Reader 语音编排](../../video_reader/reader.py#L525)、[分块](../../video_reader/reader.py#L633)、[recognition](../../video_reader/recognition.py#L13)、[任务 source 验证](../../reading_tasks/consume.py#L98)、[OCR 就绪判断](../../video_reader/reader.py#L413)、[doctor](../../video_reader/cli.py#L195)、[MCP 预导入](../../video_reader/mcp_server.py#L405)、[旧说明](../../video_reader/mcp_server.py#L176)。

### 04 任务与调度仍读取其他模块的内部状态

Scroll Background 直接查询 `task_runs`、解码 payload、比较 task identity，并调用 `Consumer._verify_task`。这些信息确实服务恢复和短重试，但 Consumer 的公开状态投影尚不能表达全部需要。

任务消费器又直接调用 `content._validate_assets`，了解 manifest 的 CID 字段，自己计算帧哈希。Controls 扫描 Reader job 文件并读取内部 JSON。模型本身换代不必改变这些关系，但材料身份、证据布局或检查点演进会向外扩散。

最小建议：Consumer／Controls 提供所属状态的公开查询与恢复判断；Reader 提供绑定资产校验、绑定补证和完整的活跃作业查询。现有 job list 只取最近 20 项，不能直接拿它替换活跃扫描，否则会漏项。保持事务原子性和当前许可政策。

依赖图还发现 `Reader.consume_task → Consumer → Queue → Reader` 的静态环。CLI 到 Scroll 的边属于兼容转发，Reader 到 Consumer 目前承担复用 job worker 的接线。它们都不是启动死循环的证明。后续增加业务 job 时，可将 handler 接线放在组合入口；不为消除图中的环立即重写作业系统。

位置：[Background 私有查询](../../scroll_agent/background.py#L83)、[恢复判断](../../scroll_agent/background.py#L171)、[消费补证](../../reading_tasks/consume.py#L213)、[前台 job 扫描](../../reading_tasks/control.py#L162)、[job list](../../video_reader/jobs.py#L210)、[反向接线](../../video_reader/reader.py#L61)。

### 05 宿主错误规范化分散到消费业务

host_runtime 产生 timeout／transport／failed 类别。Consumer 再从异常文本识别 quota、usage limit、429 等字样以暂停阅读；Background 按类别选择短重试。替换宿主适配器或改变错误文案，可能要求修改业务层判断。

最小建议：宿主通路统一规范稳定的错误类别和结构化详情，消费层执行既定暂停与重试政策。保留平台错误与模型额度的区分；不自动切模型或转云。

位置：[HostError](../../video_reader/host_runtime.py#L40)、[额度文案匹配](../../reading_tasks/consume.py#L371)、[短重试类别](../../scroll_agent/background.py#L153)。已有测试覆盖 usage-limit、平台 429 隔离和连接超时，未证明跨宿主错误格式均已统一。

## E 已登记方向可以沿现有架构推进

### 06 交付投影和完整证据会重复发送同一像素

超大 reading 结果先发可读投影，随后完整页再次包含这些图像；MCP pack 按页附加像素。本轮合成复现再次确认：**2 张源图生成 4 个 MCP 图像块**。这证明交付重复，不证明模型计费次数、主聊天重放次数或可节省比例。

最小建议：在 delivery／MCP 的交付契约内区分完整材料记录与本轮图像附件。按稳定资产身份标明已交付图像，继续保留无损原文、完整元数据与显式补取。去重范围必须可解释；不能用进程全局“发过”集合推定新聊天已经收到。

位置：[reading_page](../../video_reader/delivery.py#L89)、[pages](../../video_reader/delivery.py#L153)、[pack](../../video_reader/mcp_content.py#L9)。与[已登记上下文调研](../../research/moondigest-context-20261108/report-source.md)一致。

| 已登记方向 | 当前约束与局部落点 | 应保留的关系 |
|---|---|---|
| 分层提速与全任务损耗 | content 的冷目录仍准备 dense 预览，Consumer 先补齐语音、再固定每 4 块读一包。任务选块与包大小应在任务策略内验证，文字导航与按需视觉准备在 Reader 内区分 | 完整笔记仍覆盖必要全文；队列身份、领取和原子提交可继续复用 |
| 视觉证据生命周期 | 原图进入独立短会话、主会话接收可回查记录，可复用共享宿主通路。新增调用代价、重复交付与宿主历史重放要分别测量 | 主聊天既有图片由宿主管理，Reader 无法追溯删除；短会话结果不能冒称主宿主亲自看图 |
| 回答级溯源与按需补看 | 现有来源／分 P／时间／修订／资产身份可复用；补充本次成功交付、观察者及结论到证据的对应关系 | 材料存在、宿主收到、宿主报告观察、证据支持结论是不同层次 |

固定全文消费是当前完整笔记策略，不一概判为错误。它尚不能直接代表按任务选块策略。应先在 Consumer 内验证替代策略，再决定是否需要提取独立对象；无需预建通用 planner。

校对 evidence 验证目前主要确认同会话材料及快照，并非回答级的本次请求收据。将来实施引用时，至少关联来源身份、材料修订、源时间、资产身份、本次交付与观察记录。语义支持仍由宿主判断。该缺口属于已登记方向，不能据此声称现有校对已经失效。

依据：[content 冷准备](../../video_reader/content.py#L43)、[Consumer 准备](../../reading_tasks/consume.py#L181)、[固定分包与补证](../../reading_tasks/consume.py#L299)、[无图整理](../../reading_tasks/consume.py#L331)、[现有 evidence 校验](../../video_reader/review.py#L152)、[帧寻对照](../../research/zhenxun-comparison-20261108/report-source.md)。

## F 发布与验证有两处具体缺口

### 07 下一版源码候选缺少已实现能力的运行入口

候选构建自动收入业务包、测试和顶层文档，却固定枚举 tools。本轮静态重放选择规则，确认会收入后台代码与操作文档，同时漏掉六个运行脚本：

| 漏项 | 用途 |
|---|---|
| `tools/install_scroll_task.ps1`、`tools/run_scroll_daily.ps1` | 日轮计划任务的安装与执行 |
| `tools/manage_scroll_background.ps1`、`tools/run_scroll_background.ps1` | 后台管理与执行 |
| `tools/scheduled_task_action.ps1`、`tools/run_scheduled_hidden.py` | 共用无窗口启动链 |

最小建议：保留白名单以隔离私密配置，补齐既有能力所需运行入口，并校验这些入口及其依赖是否完整。该项阻碍按当前源码制作完整新包；不据此判断 11 月 4 日发布资产失败。

位置：[构建选择](../../tools/build_candidate.py#L10)、[后台文档入口](../../docs/background-consumption.md#L52)、[分发测试现有范围](../../tests/test_distribution.py#L20)。

### 08 策略一致性测试会重写正式适配器

`test_reading_policy_is_shared_by_mcp_skill_and_generated_adapters` 将真实项目根传给 build，生成函数会写正式 integrations 目录。这让验证夹具与安装资产产生不必要耦合。

最小建议：使用临时核心，复制真实两份 Skill 作为测试输入，其余运行文件用夹具。已有插件测试采用这种隔离模式，可以直接复用。本轮通过审计 runner 重定向该测试的构建目标，保留断言与测试源码。

位置：[实际根目录调用](../../tests/test_reading_tasks.py#L115)、[生成器写入](../../tools/build_plugins.py#L43)、[现成临时夹具](../../tests/test_plugins.py#L14)。

## G 建议按变化类型安排最小改进

| 变化 | 应局限的修改 | 相关验收 |
|---|---|---|
| 同框架换权重 | 模型配置、安装身份、所属能力缓存 | 新模型新轨；旧校对可回查；同路径升级有明确行为 |
| 换 ASR 框架 | ASR 适配、归一化诊断与能力元信息 | 原始生成、对齐、接缝、空结果和未定位候选如实保留；不能提供的词时间／概率标为未知或不可用；任务库和 Inbox 无需调整 |
| 换 OCR 框架 | OCR 适配、profile、阈值政策与 warmup | 三层派生缓存一致换代；原图、旧核验可回查；上层通过能力状态判断 |
| 改选块／分包策略 | Consumer 内的任务消费策略 | 完整任务不漏覆盖；暂停、恢复、唯一结果不退化；比较全任务损耗 |
| 换宿主传输 | host_runtime 适配与错误规范化 | 图像、结构返回、期限、额度暂停和连接重试契约保持明确 |
| 增加回答引用 | 任务／宿主的结论证据关联，Reader 提供绑定材料 | 引用来自本次成功交付；补看可回原资产；引用有效不等于事实已认证 |

建议顺序：先处理 01／02 的升级身份保证；沿已登记方向先修 06 的重复交付，再用 03／04 的窄契约承接实际能力变化；宿主变化时处理 05；发布前处理 07，测试维护时处理 08。它是本次审计建议，不替换路线中的用户排期。

目前不建议增加独立服务、消息总线、重型数据库、动态模型插件系统或全局仓储层。再少会丢掉已确认的恢复和证据职责；再多暂缺真实消费者与收益依据。

## H 验证证据与结论边界

四个有限复现均已执行并断言结果：配置漂移、OCR 缓存、图像重复、候选入口缺失（本地证据：`validation/architecture-audit-20261108/probe-evidence.json`）。脚本不调用真实模型、网络、调度或发送；只生成临时合成图及审计证据。

现有测试共发现 **417 项：415 项通过，2 项真实 stdio MCP 协议用例待验证，0 失败、0 错误**。测试按有效执行结果接续：前段 208 项通过，后段 209 项含上述 2 项跳过。测试源码与生产代码未改，隔离调整记录在 test-summary.json（本地证据：`validation/architecture-audit-20261108/test-summary.json`）。

原始套件因沙箱默认临时目录 WinError 5 中止。转用工作区临时目录后，真实 stdio MCP 握手未完成；本轮将两个相关协议用例列为待验证，不判断其产品根因。策略一致性测试的正式构建目标被隔离到临时夹具。调整仅在审计 runner 内，生产代码与现有测试源码未改。

已有测试用于核对来源／校对隔离、材料身份、无损分页、幂等提交、暂停晚包、短重试和薄适配等保障。它们不证明真实 ASR／OCR 准确率、供应商余额、连续后台稳定性或提速收益。本轮没有重跑真实视频任务，也没有更改模型、配置、后台许可或发送。

| 证据 | 用途 |
|---|---|
| 结构证据（本地证据：`validation/architecture-audit-20261108/structure-evidence.json`）／生成脚本（本地证据：`validation/architecture-audit-20261108/audit_structure.py`） | 核对源码指纹、导入关系及静态环 |
| 有限复现（本地证据：`validation/architecture-audit-20261108/probe-evidence.json`）／复现脚本（本地证据：`validation/architecture-audit-20261108/audit_probes.py`） | 回查四个具体结论及其边界 |
| 测试摘要（本地证据：`validation/architecture-audit-20261108/test-summary.json`）／已完成前段（本地证据：`validation/architecture-audit-20261108/completed-prefix.txt`）／后续日志（本地证据：`validation/architecture-audit-20261108/isolated-tests.txt`）／隔离 runner（本地证据：`validation/architecture-audit-20261108/run_checks.py`） | 核对本次执行结果、测试调整与待验证项 |

本轮只新增审计产物和知识路由入口。没有重构、提交、推送、发布，也没有把建议自动变成持续实施授权。
