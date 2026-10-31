---
template: doc
title: dsh-bili-scroll 实现调查与借鉴判断
description: 2026-10-22 · 固定源码案例，结合已有取数分层 Spike；不是安装或功能发布。
lang: zh
---

## A 结论：借鉴选片与记录，不引入另一套阅读和社交系统

**scroll 的主要价值是选片编排与使用体验，不是更强的视频理解。**
推荐借鉴三点：少量带理由的候选、包含淘汰理由的本地记录、失败与缺项可见。
工具权限收窄和有界历史读取也有价值。
这些应放在现有薄插件与共享核心之上，不另装 scroll 作为第二套服务。

本次检查固定提交 `2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c`。
[package.json](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/package.json) 中版本为 2.0.2。
这是本次案例检查的版本，不与上轮 whale 调研混为一项。

对照依据为已有的[账号行为 Spike](../account-behavior-20261022/report-source.md)和[分层原型](../acquisition-prototype-20261022/report-source.md)。
后者已有三条轻预览、两条社区材料对照和 14 项隔离测试。
本轮只补源码案例，没有新增 B 站探测或复跑视频。

## B 实现实际怎样工作

```flow
DSH 手动入口或时间窗口 -> 创建 headless 会话: 带设置和选片章程
创建 headless 会话 -> 关键词搜索: 默认近期主题意图
关键词搜索 -> 字幕取数: 首个分 P 的文字内容
字幕取数 -> 本地 ASR: 开启且依赖就绪时
字幕取数 -> 宿主选片: 章程还要求补看评论
本地 ASR -> 宿主选片
宿主选片 -> 报告和本地台账: 记录入选与跳过
报告和本地台账 -> 平台投递或收藏: 配置启用时才进入
```

它将选片规则交给宿主模型，Python MCP 提供取数和账号工具。
JS 层负责配置、窗口调度、报告解析和交互界面。
不是在本地训练或部署一个推荐模型。
[编排与工具白名单](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/index.js#L925)

需要区分“代码保证”和“提示词要求”：

| 方面 | 源码事实 | 判断 |
|---|---|---|
| 候选召回 | 搜索函数请求第 1 页，可选排序；未返回发布时间，也未传日期筛选 | 近期优先主要是选片意图，不能当成可靠的七日过滤 |
| 账号推荐 | 这条选片主链是关键词搜索，不是账号首页推荐召回 | 不能代替我们已选的账号推荐＋本地偏好 |
| 阅读材料 | 字幕函数拼接文本，输出段数，但丢弃逐段时间；ASR 同样只拼文本 | 适合文字筛选，不能替换当前时间戳阅读与返读 |
| 权限 | 环境变量控制 MCP 工具注册，条件开放评论和私信 | 比只在提示词里禁止调用更实在，但不是完整账号授权系统 |
| 配额 | 自动 tick 检查入选量；提示词告知剩余量；报告标题参与计数 | 入选量不是请求预算，也不是跨宿主事务限额 |

依据：[搜索](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/vendor/bilibili-mcp/mcp_server.py#L265)、[字幕](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/vendor/bilibili-mcp/mcp_server.py#L385)、[ASR](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/lib/asr.py#L109)、[配额计数](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/index.js#L724)。

## C 值得借鉴什么，怎样接到已有 Spike

| 借鉴点与证据 | 与已有实验的关系 | 建议吸收方式 | 收益判断 |
|---|---|---|---|
| 少量候选＋简短价值判断；[章程](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/prompts/duty.md#L61) | 新推荐候选已有足够轻材料，决定暂缓深读 | 在当前聊天给少量候选，说明推荐理由、材料范围及缺口 | 高；直接降低用户筛选负担 |
| 入选与淘汰都留理由；[归档约定](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/prompts/duty.md#L156) | 原型只保存了 5 条 Agent 观察，尚无真实用户反馈 | 在共享核心中记录发现、预览、阅读、推荐及反馈，避免重复处理 | 高；支持中断后恢复，减少重复处理 |
| 近期台账与历史归档分开；[rollSeen](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/index.js#L1626) | 续看与离线复用已证明有收益 | 交给代码按 BV、分 P 和状态查重，只给宿主相关小窗口 | 中高；避免每轮读取无限增长的全文台账 |
| 失败留可见结果；[宿主补报告](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/index.js#L1160) | 原型已区分空样本与限制响应 | 保留本轮失败原因、缺材料数量和可继续方式，不强制生成笔记 | 高；避免无结果却不知原因 |
| 评论部分失败仍带错误；[返回路径](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/vendor/bilibili-mcp/mcp_server.py#L370) | 两条社区样本证明有时有用、有时收益为零 | 保留成功空、部分结果、取数失败等状态；评论依旧按需 | 中；补强现有状态语义，不增加默认取数 |
| MCP 注册级能力白名单；[注册器](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/vendor/bilibili-mcp/mcp_server.py#L44) | 本项目目前无平台互动工具 | 继续保持账号读写分离，不为推荐顺带增加写工具 | 边界价值高；现在无需增加新权限框架 |
| 定制章程采用指纹更新；[ensureCharter](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/lib/state.mjs#L128) | 当前 Skill 从单一源稿生成薄包 | 仅在未来允许用户定制模板时考虑保留修改与旁存新版 | 低优先级；不为此复制脚本、环境和模型 |

“入选上限”可以作为用户注意力预算的参考。
它要与网络请求、下载字节和转写成本预算分开。
不照抄具体的每日条数、时间窗口或过期天数。

## D 不值得照搬，以及需要纠正的假设

**不能照搬空文本等于无语音。**
章程将空转写或署名行判为无语音，并要求直接跳过。
停止无意义重试是对的，但这个内容结论过强。
空结果也可能来自字幕缺失、VAD、识别失败或语言问题。
我们的状态应是“未取得可用语音，原因待定”，不能据此断言无声。
[对应章程](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/prompts/duty.md#L75)

| 不照搬的部分 | 代码依据或局限 | 对本项目的处理 |
|---|---|---|
| 每条顺手读评论 | 章程默认补评论，工具默认取 30 条；循环可分页 | 仍按问题补少量评论，弹幕后置；不增加默认开销 |
| 报告文字作为业务事实来源 | 正则统计标题、解析台账状态；关日报时自动运行另有保守限制 | 用结构化本地记录，报告只做派生展示，不让格式影响状态和配额 |
| 每次全文扫描与 30 天外不再判重 | 历史归档降低上下文，但旧记录仅留档 | 保留按需查询旧历史的能力；近期窗口不是永久遗忘 |
| 另建 ASR 与临时媒体链 | 独立环境、CPU Whisper、下载音频后删除；输出无时间段 | 复用现有核心、模型、登录和媒体缓存，不引入第二套下载转写 |
| DSH 调度、自动评论收藏与双向社交 | 源码包含写接口与后台监听，已超出选片阅读本身 | 不整套引入社交系统；单向私信投递的后续澄清见 G 节，不补造播放 |
| 用轮次和入选量替代平台控制 | 调度窗口与工具超时不覆盖所有请求 | 继续保留正式共享预算与受限暂停这一整合缺口 |

表中依据：[评论工具](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/index.js#L562)、[自动 tick](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/index.js#L1271)、[本地 ASR](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/lib/asr.py#L57)。

还有两个容易误读的权限细节：

- 自动评论默认关闭，但配置的投递模式默认是私信。白名单按配置可能包含发送私信；不能把整个默认形态称为纯只读。
- MCP 的工具名单为空或未配置时会注册全套工具。只应借鉴明确收窄能力的做法，不把该默认机制直接移植为安全边界。

依据：[默认配置](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/index.js#L49)、[名单生成](https://github.com/c1overzz/dsh-bili-scroll/blob/2d71abd25bee19a6bdc0c586b7d6e11c5ee4499c/index.js#L1062)。
这些是静态实现事实，不是对实际账号发送行为的测试结论。

## E 对现有产品结论有何改变

**不改变上一轮的总体方向，补强选择理由与状态记录。**
继续以账号推荐＋关键词搜索召回，缓存优先，必要时轻预览。
值得继续的候选才进入现有深读；评论作为独立旁路。

scroll 对“挑完怎样让用户看懂、下次怎样不重复”给了具体参考。
但它没有证明我们的推荐会更符合真实兴趣。
其关键词和人格提示不能替代用户反馈，也不是偏好学习效果验证。

后续若获授权正式整合，值得验收的是三个小场景：

1. 推荐一两条时，用户能看到选择理由、已用材料和缺口。
2. 再次请求推荐时，已推荐、已读、仅预览的记录不混淆；本地失败不算没记录过。
3. 用户明确反馈能改变下一轮选择；材料空缺与平台受限不会被写成内容不存在。

这三项是案例产生的候选验收点，不是本轮新增实施计划。
当前核心仍 0.6.2，薄插件仍 0.1.0，八个 MCP 工具不变。

## F 调查证据、许可和验证范围

本轮先走 AGENTS → registry，再读取两份指定研究报告和既有来源清单。
本地源码检索仅限新下载的 scroll 快照，没有全项目递归搜索。
按函数和调用路径定位后读取行号上下文，不只看 README 宣传。

通过 GitHub API 固定提交和目录树，再按提交下载 19 份源码与许可文件。
没有安装依赖、执行上游脚本、读取其账号文件或访问 B 站。
最初沙箱内域名解析失败，随后获准联网读取 GitHub；没有借此修改代理或登录配置。

- [来源与提交](source.json)：仓库地址、提交、抓取时间。
- [文件清单](files.json)：19 份下载文件的 SHA-256 和字节数。
- [完整目录树元数据](tree.json)：下载选择的依据，不代表每个文件都做了完整评审。
- [本地固定源码](source/)：保留原始内容与行号；上游 AGENTS 和提示词仅作为研究材料。
- [文档与证据检查](checks.json)：来源完整性、引用行号和正式落点的相关链接。

主要阅读范围为 index.js、选片章程、MCP 注册与取数函数、状态维护、ASR，以及投递和收藏路径。
下载 client.js 等文件作留档，不声称逐行审查整个 UI 或全部 vendor 工具。
这是静态源码调查，没有运行上游 selfcheck，也没有做运行时推荐质量、免风控或安全审计认证。

上游本体及内置 bilibili-mcp 均提供 MIT 许可，源码快照中保留各自 LICENSE 与 NOTICE。
本次只存研究副本，没有将源码并入运行组件或插件包。
检查不会证明平台授权或长期可用；前述平台边界继续适用。

## G 用户澄清：私信可作为轻量投递出口

用户明确不需要自动评论和收藏，并要求以日常、轻便、易用为准；同时询问能否做私信投递。前一版把单向投递与社交互动一起排除，表述过宽。

据此保留“组件小号向指定主号发送简短推荐”的候选方向，不整套引入 scroll 的轮询、双向聊天或 DSH 服务。共用现有核心、登录、模型及缓存；当前聊天仍可直接看推荐，私信是可选出口。

正式接入前需指定收件账号并验证一次实际收件；保留简单发送记录，不因失败改发公开评论，也不反复重试。本次只澄清范围，没有新增发送工具、后台任务、账号测试或任何实际发信。自动评论、收藏不列入当前产品范围。用户原话与授权边界主维护于 docs/decisions.md。
