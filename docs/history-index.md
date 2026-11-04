# 研究、验收与历史索引

身份：按需回查证据，不承担当前状态与下一步。历史记录中的版本、阶段和建议按当时理解；现行入口见 [registry](registry.md)。

## 调查与真实案例

| 知识或职责 | 位置 | 何时读取 |
|---|---|---|
| storyboard 整体意图与阅读缺口 | [整体评估](../research/storyboard-20261027/report-source.md)、[意图与缺口](../research/storyboard-20261027/intent-and-gaps-source.md)、[固定来源](../research/storyboard-20261027/source.json) | 查观察动作、图文交付、可读性/续读及既有底层复用；材料为当时对照，采用项和实施顺序回到当前路线 F 节 |
| 独立工具、输入输出与跨宿主对比 | [跨领域调研](../research/standalone-reader-20261024/report-source.md) | 比较同类工具、通用材料结构、长任务及不同 harness 接入时；当前方向与状态回到决定和路线 |
| 账号行为与取数分层 Spike | [研究报告](../research/account-behavior-20261022/report-source.md)、[脱敏在线探测](../research/account-behavior-20261022/account-probe.json)、[固定版本来源](../research/account-behavior-20261022/sources.json) | 接账号推荐、本地偏好、轻预览、评论弹幕前；区分已选方向、候选设计、平台许可与可用性 |
| DSH 视频插件生态扫描 | [生态扫描报告](../research/dsh-video-ecosystem-20261031/report-source.md)、[来源与抓取时间](../research/dsh-video-ecosystem-20261031/source.json) | 判断 DSH 侧哪些能力已被他人独立实现、哪四项仍空缺、要不要加第三套薄插件时；README 与市场页级扫描，未固定提交、未核源码，不可作为实现事实引用 |
| 选片编排参考案例：dsh-bili-scroll | [实现调查](../research/dsh-bili-scroll-20261022/report-source.md)、[固定提交](../research/dsh-bili-scroll-20261022/source.json)、[源码指纹](../research/dsh-bili-scroll-20261022/files.json) | 查选片理由、去重与历史查询、失败状态、工具白名单及不照搬的社交与阅读链路时；静态案例，不是已接入能力 |
| 内容学习与发布渠道案例：dsh-bili-humanism / B站鱼灾 | [案例调查](../research/bili-humanism-20261024/report-source.md) | 查通用材料交付、按需披露、原片回查、宿主权限及发布渠道版本差异；含原笔记项目判断的取舍与路线去重，非新增实施任务 |
| 输出复用真实缺陷：VR-OUTPUT-20261024-01 | [缺陷记录](../research/output-reuse-20261024/report-source.md)、[实物证据](../research/output-reuse-20261024/evidence.json) | 查校对版本选取、缓存资源依赖、HTML 源稿可移植性与下游证据关联；0.10.0rc1 已实现显式修订导出并通过 86 图实际案例；历史缺陷记录保留 |
| 取数分层与产品体验原型 | [综合报告](../research/acquisition-prototype-20261022/report-source.md)、[汇总](../research/acquisition-prototype-20261022/results/summary.json)、[运行边界](../research/acquisition-prototype-20261022/README.md) | 查三条轻预览、社区材料收益、离线复用、索引偏移、14 项隔离测试和推荐产品形态；不是正式 MCP 接入或推荐质量证明 |
| ASR 与校对方案调查 | [研究报告源稿](../research/asr-correction-20261021/report-source.md) | 比较引擎、参考项目与已失败探测时；报告建议不是自动授权 |
| 本地 ASR 引擎首轮对照 | [实验报告](../research/asr-engine-20261021/report-source.md)、[结果汇总](../research/asr-engine-20261021/summary.json) | 查首轮 Windows/GPU、无对齐原文及历史参数时；新进展看下一行 |
| Qwen 独立参考、对齐与边界 | [本轮报告](../research/qwen-foundations-20261021/report-source.md)、[汇总](../research/qwen-foundations-20261021/summary.json)、[运行说明](../research/qwen-foundations-20261021/README.md) | 查冻结人工参考 CER、官方 ForcedAligner、重叠切分、显存约束及动态/原生声音缺口时 |

## 2026-10-30 至 11-03 诊断与使用证据

| 证据 | 适用范围 |
|---|---|
| [共享运行任务](../validation/runtime-jobs-20261030/report-source.md)、[rc6 修复](../validation/diagnosis-repairs-20261031/report-source.md) | 任务状态与接续、独立处理/消费评估、后续修复及真实复验 |
| [ASR 同窗追查](../validation/asr-followup-20261031/report-source.md) | 联网依据、强制语言退化和后处理遮蔽；策略修复尚未实施 |
| [双片阅读观察](../validation/reading-pair-20261103/report-source.md)、[攻略选图复验](../validation/guide-image-selection-20261103/report-source.md) | 已读材料、默认深检查与材料锁、准星帧和闪光结果的选图边界 |
| [Scroll 状态观察](../validation/scroll-state-20261103/report-source.md) | 日推失败上层错误、用户网络线索及 preparing 遗留快照；非根因诊断结论 |
| [本轮文档维护](../validation/docs-20261103/summary.json) | 主维护文档同步、交接归档及文档核对范围；不充当功能验收 |

## 2026-10-28 实现与阅读证据

[2026-10-28 真实阅读与 Scroll 比较](../validation/task-reading-20261028/report-source.md)、[汇总](../validation/task-reading-20261028/summary.json)、[跨聊天接续材料](../validation/task-reading-20261028/resume-check.md)：查完整数学/软件/长访谈、关键错误修正、两片比较及人工复核范围。

[2026-10-28 文档与候选更新](../validation/docs-20261028/summary.json)记录 10 月 28 日文档整理及当时生成的源码候选，不含 10 月 29 日修订。功能验收仍按下面各版本证据，不因改文档重复宣称测试。

[0.10.0rc2 修复验收](../validation/reader-0.10.0rc2/report-source.md)记录真实漏句根因、区间校对、增量保全、入口同步和更新后的发布候选。

[0.10.0rc1 验收](../validation/reader-0.10.0rc1/report-source.md)记录真实平台、双宿主、完整交付、Scroll 批次、干净安装、保全与发布候选。历史报告仍只说明对应版本。

## 版本证据与历史

| 知识或职责 | 位置 | 何时读取 |
|---|---|---|
| Windows MCP 子进程与 OCR 启动修复 | [正式验收](../validation/stdin-fix-20261024/report.md)、[安装记录](../validation/stdin-fix-20261024/install.json) | 排查 yt-dlp/FFmpeg 管道继承阻塞、NumPy 首次导入死锁；含原文件备份及 31 项测试 |
| Windows MCP / CLI UTF-8 修复 | [验收与边界](../validation/utf8-20261027/report.txt)、[安装记录](../validation/utf8-20261027/install.json) | 查 -I 忽略环境编码、转写日志导致 stderr 断开、统一进程入口及新进程实测；旧连接须重连 |
| 0.7.0 集成基线历史 | [当时报告](../validation/agent-0.7.0/report-source.md)、[汇总](../validation/agent-0.7.0/summary.json) | 查首次真实选片、SQLite 记忆、三轮收件、隔离区间唤醒；当前 API / 日常状态见 0.8.0 运行说明 |
| 0.6.2 可选引擎验收 | [0.6.2 可选 Qwen 接入](../validation/qwen-0.6.2/report-source.md)、[最近实测指针](../validation/qwen-0.6.2/latest-run.json) | 查可选引擎、三条短视频、108 项测试及投入边界时 |
| 返读优化基线 | [0.6.1 返读优化](../validation/reading-0.6.1/report-source.md)、[结构化汇总](../validation/reading-0.6.1/summary.json) | 查 source 一致性、按需 OCR、真实对照及该版 77 项测试时 |
| 自主检索与陌生视频验收 | [0.6 检索与陌生视频验收](../validation/discovery-0.6/report-source.md)、[结构化汇总](../validation/discovery-0.6/summary.json) | 核对搜索、热门、真实 MCP 与自主发现至校对追问时 |
| 校对与复听实现基线 | [0.5 汇总](../validation/correction-0.5/summary.json)、[验收报告](../validation/correction-0.5/report-source.md) | 追查具体校对实现与旧版本覆盖时；不是通用准确率证明 |
| 早期真实案例与基础能力 | [案例汇总](../validation/real-video-cases-20261021/summary.json)、[0.4 汇总](../validation/foundations-0.4/summary.json) | 追查字幕、动画及完整阅读基线时 |
| B 站独立登录证据 | [0.3 验收](../validation/bilibili-auth-0.3.json)、[平台参考](reader-reference.md#平台配置与云端选项) | 修改账号、续期或判断已测登录场景时 |
| 早期产品构想 | [原稿](刷视频agent-idea.md) | 追溯 BiliLearn 底座设想和早期范围；不作当前实施依据 |
| 历史交接 | [截至 2026-10-24 的汇编](history/handoff-through-20261024.md) | 查旧会话 ID、阶段命令和当时状态；当前接续读 handoff |
| 入口整理过程 | [2026-10-21 记录](get-start-20261021.md)、[2026-10-24 整理](../validation/docs-20261024/report.md) | 追查入口职责、初稿、自检与改动依据，不作日常必读 |


## 2026-10-29 归档

- [10 月 28 日前决定全文](history/decisions-through-20261028.md)
- [10 月 28 日前交接全文](history/handoff-through-20261028.md)
- [10 月 28 日路线全文](history/roadmap-through-20261028.md)
- [本次文档整理](../validation/docs-20261029/summary.json)

## 2026-11-03 交接整理

[截至 10 月 31 日的交接快照](history/handoff-through-20261031.md)保留本次整理前的内容；当前接续统一读 handoff。
