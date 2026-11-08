---
title: 帧寻：溯源性读取与证据上下文
subtitle: 2026-11-08 · 已找到公开源码 · 对照当前 Video Reader
template: doc
theme: inkread
lang: zh
---

**对应的公开源码已找到：[Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper)。** 它对回答级溯源和补看的处理，比 MoonDigest 更贴近这次讨论。其浏览器子循环也提供了证据隔离的具体参考。

## A 仓库与视频对应关系

视频是 [BV1CA4W6kEQP](https://www.bilibili.com/video/BV1CA4W6kEQP)，作者 Teachmeplaycode，项目名“帧寻 GongJ!ng?”。在同名 GitHub 账号下找到对应仓库，README 的功能与演示素材相符。

本轮固定读取提交 [a3cd9f8](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/commit/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7)。源码提交时间为北京时间 2026-11-07 10:10。README 说明演示录于 10 月 27 日，**等待解析和生成的时间被剪去**，不能用成片判断实际响应速度。[演示来源说明](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/docs/media/README.md)

作者给出的体验地址是 linyi.work/ZhenXun，README 使用小写路径 /zhenxun。本轮域名解析失败，未实测线上服务；公开代码可直接检查。

## B 视频里实际展示了什么

| 演示时间 | 看到的行为 | 对我们的价值 |
|---|---|---|
| [00:35](https://www.bilibili.com/video/BV1CA4W6kEQP?t=35) | 工具记录同时列出选帧、读转写、读画面文字和细看区间 | 把材料准备与进一步取证呈现给使用者 |
| [00:51](https://www.bilibili.com/video/BV1CA4W6kEQP?t=51) | 画面、原声、画面文字使用不同引用标签，点开旁边的原片播放器 | 回答中的关键结论能直接返回原材料 |
| [01:02](https://www.bilibili.com/video/BV1CA4W6kEQP?t=62) | 用户追问操作先后，工具记录请求细看原教程 02:11–02:31 | 把疑点收窄到局部，而非重读整片 |
| [01:05](https://www.bilibili.com/video/BV1CA4W6kEQP?t=65) | 回答列出事件顺序，也说明无法确定按键的精确瞬间 | 保留“看到了什么”和“还不能确定什么”的区别 |

_图：演示 00:51：不同类型的时间引用，以及内嵌原片回看。原截图与读取材料保留本地，未随源码提交。_

图源为用户指定的作者演示视频。**演示的 00:51 与标签里的教程 01:32 属于两条时间轴**，溯源记录必须绑定正确来源，不能只存一个时间字符串。

_图：演示 01:05：补看后的事件顺序，以及未能确定的细节。原截图与读取材料保留本地，未随源码提交。_

## C 源码中最值得参考的三处

**回答引用有类型。** 提示与解析器区分画面、原声、画面文字、外部资料、知识和推断。回答完成前，校验器检查时间范围、附近材料和本次出现过的外链；前端把失败引用显示为缺少证据，避免继续呈现有效链接。[引用校验器](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/backend/modules/agent/evidence.py#L80)、[前端引用处理](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/front/src/lib/markdown.jsx#L103)

**补看有明确入口。** view_frames 在局部时间段取最多 6 帧，replay 用更密的连续取样处理动作顺序。显式时间问题会在正式回答前补帧；这弥补小模型未必主动调用工具的问题。原片取不到时会标明退回已有关键帧。[局部取帧](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/backend/modules/agent/tools.py#L763)、[回答前补看](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/backend/modules/agent/run.py#L596)

**已有材料可以先回答。** 简要概览采用较小图像与文字预算，章节摘要只作导航。所需范围已有材料时不等全部解析，只有完全没有可用证据才短暂等待。[response_plan.py](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/backend/modules/agent/response_plan.py#L11)、[wait_for_material](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/backend/modules/agent/run.py#L488)

这些做法与我们已确认的“及时回答、按疑点深入”一致。可借鉴的是编排、证据标签与回查体验，无需为此复制整套学习工作台。

## D 溯源还要区分三个层次

**材料存在、模型收到、材料支持结论，是三个不同判断。** 帧寻的引用检查有实际价值，但主要证明引用附近有材料，不能自动保证结论正确。

代码有两处具体边界：画面检查读取任务中全部 status=ok 的帧，不核对这一次实际发送的所选帧；补看区间在工具输入事件时登记，此校验器没有再确认工具成功和实际返回的图像清单。[check 与 with_evidence](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/backend/modules/agent/evidence.py#L80)

因此不宜照搬“引用已核对”作为语义保证。我们的后续设计应把引用绑定到**本次成功交付的证据**，再让宿主判断材料是否支持结论。宿主返回观察 ID 也不能单独证明理解正确。

```flow LR
源材料与修订 -> 本次交付清单
本次交付清单 -> 宿主观察记录
宿主观察记录 -> 结论与证据对应
结论与证据对应 -> 可定位的回答
可定位的回答 --> 原材料复核
```

按当前 Reader 的基础，来源、分 P、时间、帧 ID、像素哈希与校对修订可以继续沿用。新增工作主要是从材料级回查延伸到回答中的具体结论，不把引用标签当成事实认证。

## E 它怎样处理图像上下文

| 路径 | 源码事实 | 对证据隔离的意义 |
|---|---|---|
| 历史问答 | 只带最近 8 条文字消息，每条最多 4000 字符 | 旧附件不会随历史无限累积 |
| 每次视频提问 | 重新选择画面，重新放进当前请求；概览通常限 12 或 16 张，普通路径上限默认 64 张 | 重复选择的源图仍会再次输入 |
| 同一回答的工具循环 | 反复发送同一个 messages，补图继续追加；没有移除旧视频图像 | 一次工具调用后继续回答，初始图像就会再次出现在模型请求中 |
| browse 工具 | 独立小循环处理网页；导航后把旧截图和后续旧页面快照改成占位文字 | 这是具体可用的上下文管理参考 |
| browse 返回主问答 | 返回结论与访问过的页面，截图通过展示事件传给前端 | 网页截图没有作为图像工具结果进入主模型 |

视频主循环默认最多 4 轮工具，另有最后回答和特定重试、续写路径。图像出现次数取决于走了哪些路径，不能把“一次用户问答”当成“一次模型调用”。[视频请求组装](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/backend/modules/agent/run.py#L340)、[工具循环](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/backend/modules/agent/run.py#L736)

```flow LR
网页任务 -> 浏览器小循环
浏览器小循环 -> 当前截图
当前截图 -> 当步判断
当步判断 -> 替换旧截图
替换旧截图 -> 浏览器小循环
浏览器小循环 -> 文字结论与来源
文字结论与来源 -> 主问答
```

这与前面提出的视觉短会话方向直接相关。帧寻已经在网页浏览中实现类似分工，**视频主问答尚未采用同样的图像隔离方式**。删旧截图也有代价：需要再次检查旧画面时必须能重取，不能只剩一段摘要。[stale 与 browse](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/backend/modules/agent/browser.py#L340)

## F 合并到我们的后续方向

| 参考来源 | 值得采用的方向 | 当前 Reader 的落点 |
|---|---|---|
| MoonDigest | 粗筛、字幕、画面逐层投入成本 | 现有轻预览、内容目录和按任务选包 |
| 帧寻的引用与补看 | 结论标来源类型，失败引用可见，疑点回到局部原片 | 宿主回答约定、导出产物和证据记录 |
| 帧寻的浏览器循环 | 子上下文看图，替换旧截图，主上下文只收可回查结果 | 复用共享宿主通路与通用任务编排，验证视觉短会话 |

建议将“回答级溯源”与“上下文成本”一起验证。每个关键结论保留来源类型、材料身份、时间范围、证据资产、本次观察者和不确定项。原图可以保存在主上下文之外，追问时仍能沿原资产重新取证。

提速还有一个独立参考：它用 FFmpeg 从远程流按时间定位取帧，常规图宽 640，细节图按源尺寸取到最大 3840。可比较这种方式与我们现有的原生预览、完整媒体缓存；远程可用性和反复读取成本需要实测。[grabber.py](https://github.com/Teachmeplaycode/ZhenXun-GongJing-Video-Tutorial-Helper/blob/a3cd9f8bea3d05ee9ff767e6584ca69f9b6d59c7/backend/modules/frames/grabber.py#L46)

它的分流、语音、OCR、主问答和浏览器循环都可能产生开销。需要比较完成同一任务的总耗时、总输入和事实质量，不能仅据子循环或较小模型认定整体更省。

## G 本轮证据与限制

本轮读完了 61 条自动字幕，检查了初始 11 帧和 4 张局部精确帧，并查看原生预览。没有逐段复听或完成全文语义校对，不声称连续观察全片。

源码检查覆盖引用校验、视频组包与工具循环、浏览器旧图移除、概览预算、分流、取帧和前端引用呈现。未安装或运行上游应用，未执行其测试，也未对两项目作性能排名。

网页检索最初未命中对应仓库，最终通过作者账号的公开仓库搜索找到。评论第 1、2 页均标记 partial，没有把它们视为完整讨论区。

固定提交、文件 blob 身份、Reader 会话和重点帧记录在 `evidence.json`（本地留证）。前一轮结论见 [MoonDigest 与当前上下文调查](../moondigest-context-20261108/report.html)。后续方向已补到[路线](../../planning/roadmap-20261021-source.md)，本轮没有改生产阅读逻辑。
