# Sense Now、See Now 与 Video Reader 的对照

日期：2026-11-04。本批固定 `canyueY/sense-now` 的 6ae6f35 和 `SAOS-3624/dsh-see-now` 的 93342e6；核对 README、包元数据、来源声明和关键实现，共 17 个文件通过 Git blob 指纹验证。未安装第三方插件、运行媒体测试或启动屏幕/声音采集。我们的基线为 488dc8f。完整提交、文件指纹和范围见 [summary.json](summary.json)。

## 判断

Sense Now 的 `video_index` 与 Reader 有明显重叠，应作为直接对照项目，不能只归类为实时陪看。See Now 的主要产品入口是实时屏幕/摄像头陪看；Sense Now 在继承这条工作流的基础上增加离线视频索引。我们的现成接口与个人收件/任务/结果工作流不同，但时间戳、证据、按需画面和续读不是独有卖点。

这里的视频内容索引用于在视频中找证据；我们刚完成的 DSH 插件索引用于找到和安装工具。两者不是同一层能力，插件索引完成不会补上内容检索层。

## 来源关系

Sense Now 的 README 与 NOTICE 明确说明基于 SAOS-3624 的 dsh-see-now，保留上游 Apache-2.0 和作者归属。GitHub 没有将它标记为 fork，不能因此否认其声明的派生关系。当前两份源码树仍有 png.js 和 tiers.js 两个文件的 blob 完全相同；这个数只表示当前同路径文件逐字节一致，不是总相似度或代码来源比例。[Sense NOTICE](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/NOTICE)、[上游包](https://github.com/SAOS-3624/dsh-see-now/blob/93342e6122b278139281d71346314048170a034b/package.json)。

## 产品对位

| 维度 | See Now | Sense Now | Video Reader + Scroll |
|---|---|---|---|
| 主入口 | see_now，实时陪看 | sense_now 实时陪看；video_index 离线索引 | 通用阅读、独立任务与个人账号工作流，两套 MCP |
| 实时输入 | 屏幕、摄像头、文件回放，变化筛帧和拼图；悬浮窗和可选听/说 | 继承实时工作流，另有抓播与时间映射模块 | 当前不提供对应的实时陪看产品入口 |
| 长视频问答 | 未见独立持久化长视频索引工具 | 先建立可复用索引，再按问题选 chunk 和证据，支持局部补取 | 宿主按任务读取材料，分页/时间点继续；已有缓存和修订可复用 |
| 查询方式 | 连续取得近期变化图像 | 规则路由、文本打分、时间定位与预算内证据装配 | 宿主决定读什么；材料目录按来源/账号查找，不等同内容问题检索 |
| 说话人与音画线索 | 实时声音转写与画面一起交付 | 有可选说话人分离/合并和实验身份线索 | 未提供同等独立身份绑定工作流；已有转写与核查问题记录 |
| 用户待读队列、附言和结果 | 本次公开接口未见对应工作流 | 有索引/job 管理，本次公开接口未见同类收件与任务结果工作流 | reading_tasks 独立管理；Scroll Inbox 保存原消息与同步历史 |
| B 站小号与私信 | 本次公开接口未见 | B 站视频来源适配，不等于独立小号收件/回报业务 | 自主扫码登录、小号首页、主号来信和授权私信已有真实使用 |
| 接入与复用 | DSH 原生工具，也导出 Node 模块 | DSH 原生工具，导出 video-index 引擎供 Node 使用 | 已有 CLI/MCP，Codex、Claude、DSH 适配复用同一核心 |

See Now 的实时筛帧主要基于画面变化，而非语义理解；本机 CPU/token 数字是作者特定环境报告，本批不作复测或成本排行。[上游 README](https://github.com/SAOS-3624/dsh-see-now/blob/93342e6122b278139281d71346314048170a034b/README.md)。Sense Now 的注册代码确实同时挂载两个工具，索引工具明确输出证据而非独立最终答案。[注册入口](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/src/index.js#L548)、[工具协议](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/src/video-index-tool.js#L114)。

不能把它们的帧缓冲或后台索引 job 当作我们的用户待办队列；Reader 自己也有技术 job。比较任务体系时，应看附言、任务状态、处理结果与来源历史，而不是仅看是否有 queue/job 字样。

## Sense Now 值得具体研究的部分

**分块目录与两级检索。** query 先读取 catalog，用问题和时间选择块，只加载命中的 chunk，再组装受预算约束的证据。泛问有单独的时间覆盖选择，包含开头、中段、结尾，默认代表块预算为 12、硬上限 24。它提供了我们当前没有的内容检索层；这不等同语义校对或保证每段都被宿主读过。[query 主流程](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/src/video-index/video-index-engine.js#L1691)、[块选择](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/src/video-index/index-retriever.js#L215)。

**轻量查询路由。** 源码用规则识别时间、视觉、音画、深核验等问题，再用规范化词与中文片段做本地匹配打分，不另调用模型。这有明确的成本与可解释性收益；同义表达召回、纯视觉事件定位和问答正确性仍须实片验证。[路由](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/src/video-index/query-router.js)、[文本打分](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/src/video-index/index-retriever.js#L5)。

**默认能力与可用状态分开。** engine 默认实例化未配置的 OCR 与 VAD 适配器；它们会明确返回 unavailable。ASR 和说话人功能另有可选组件与开关。README 的完整能力图不能直接理解成基础安装全部就绪。[默认适配器](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/src/video-index/video-index-engine.js#L140)、[OCR](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/src/video-index/adapters/ocr-adapter.js)、[VAD](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/src/video-index/adapters/speech-activity-adapter.js)。

**一个应测的检索边界。** 无文本命中的视觉/音画/深问题会回退到靠前的 ready 块。这个回退本身不能证明后半段纯视觉事件已被查找；是否经后续补证正确定位，适合用真实教程做对照。[回退代码](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/src/video-index/index-retriever.js#L319)。

## 成熟度与性能口径

Sense Now README 报告 303 项测试，并明确网络相关使用注入或本地服务；6 小时视频的毫秒级数字是合成索引/检索开销，不含真实解码、OCR/ASR 与模型处理。本批没有复跑这些测试，不能据此和我们的真实视频耗时排序。真实长片成本、B 站账号/字幕/CDN、多人身份质量及声卡兼容性均仍需实机验证。[固定测试说明](https://github.com/canyueY/sense-now/blob/6ae6f358cff6688c2b849af4a968b40c83bb3af6/README.md#13-测试与验证实测分析)。

我们的优势也须限定到已有证据：跨宿主接口、账号收发和六项真实任务/结果已有验证；长期定时稳定性、自动后台消费和 Qwen 退化仍不能据此宣称解决。见[能力状态](../../docs/capabilities.md)。

## 对我们描述与后续评估的建议

对外可以突出组合用途：**跨宿主视频阅读组件，结合独立 B 站小号收件、通用待办与可追溯结果。** 单独强调字幕、画面、证据、按需深入不足以与 Sense Now 区分；这个组合也不是对所有项目独占性的声明。

技术上值得讨论的是轻量内容目录、块级检索和局部作业复用；实时陪看可单独考察为输入能力。是否采用仍需用户决定，本批不改变已确认的及时回答、按疑点深入体验，不新增自动索引、采集或分析模型。

若继续实测，建议同片比较：长访谈的概要与重复追问；中后段无字幕的视觉操作；字幕缺失或错误的片段。记录首答耗时、证据召回、续读/检索遗漏与复用成本。各自先确认所需适配器已就绪，不能用合成 benchmark 替代媒体任务结果。
