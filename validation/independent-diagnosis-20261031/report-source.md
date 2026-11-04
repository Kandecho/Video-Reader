---
template: doc
theme: inkread
lang: zh
title: 预览、打开失败与可疑识别的独立排查
subtitle: 2026-10-31 · 以原诊断定位样本，重新核对缓存、源码和受控请求
---

## A 独立结论

**已复现空索引缓存使原生预览持续无图，但没有复现“登录态必然导致空索引”。可疑 ASR 能重复产生；尚不能据此确认全片无口播。**

本轮以 docs/diagnosis-20261031-preview-videoshot.md 中的视频 ID、任务 ID 和现象为入口。未以其归因为前提，也未修改运行代码或识别记录。

| 原诊断说法 | 本轮判定 | 独立依据 |
|---|---|---|
| 登录态导致 videoshot 空 index，任何视频都无图 | 不成立为稳定归因 | 3 条样本的完整 Cookie 请求均返回索引；同一条省略 Cookie 的请求前后却分别为空和正常 |
| 空 index 后无法按时间取预览 | 已确认 | 原缓存 index=0、图集=2；snapshot_positions 报 snapshot_index_unavailable |
| 无口播，因此英文必然是幻觉 | 证据不足 | 独立重识别重复 3 段及其低置信标记；没有独立听觉真值，音量/画面不能证明无人声 |
| Qwen 的 no_speech 证实 Whisper 幻觉 | 不支持该推断 | 时间窗不同；Qwen 原始文字非空，零时长对齐点落在所有权区间之外 |
| open 只落材料，图片必须另 read | 源码与缓存反证 | _open 会调用 read；真实 open 交付快照的后续页包含原生图 |
| renewal=unavailable 表示无法自动续期 | 状态语义错误 | 续期实现存在；该值表示本次确认/续期请求不可用，不是永久能力结论 |

## B 预览：新请求与旧缓存分开验证

对 BV1KLxN6ZERf、BV1QHxe6jEF9、BV1Z8xA6zEpD 各做 4 组请求：完整组件 Cookie、省略 Cookie、仅移除 SESSDATA、仅保留 SESSDATA。端点、BV/CID、UA、Referer 和其他请求头保持一致，ttl=0 不复用组件响应缓存；最后再重复第一条样本的完整 Cookie 与省略 Cookie 两组。

共 14 次接口对照，全部 code=0。所有请求沿用原账号的预算、限速与暂停机制，没有切换到另一账号预算，也没有在平台拒绝后改身份重试。这里只在“成功但缺字段”的现象上改变 Cookie 变量。

| 样本 | 完整 Cookie | 省略 Cookie | 移除 SESSDATA | 仅 SESSDATA |
|---|---:|---:|---:|---:|
| BV1KLxN6ZERf | 156 | 0 | 156 | 156 |
| BV1QHxe6jEF9 | 234 | 234 | 234 | 234 |
| BV1Z8xA6zEpD | 99 | 99 | 99 | 0 |

表中为 index 条数。最后重复 BV1KLxN6ZERf 时，完整 Cookie 为 156，省略 Cookie 也为 156。因此同一省略 Cookie 条件在本轮已有不同结果；不能把空索引稳定归因于登录、SESSDATA 或某一种固定 Cookie 组合。上游为何出现这种差异尚未定位，本轮未记录可支持出口 IP、服务端实验或 CDN 缓存等具体解释的证据。

**组件内可确定的放大机制是语义失败缓存。** 历史缓存 code=0，但 index=[]，image 有 2 张图集。采样时间轴不可用，因此拒绝给出伪造秒数是正确的。然而 generic request 把这个成功 JSON 缓存下来，preview 按默认 86400 秒 TTL 继续复用它；字段有效性是在缓存之后才检查的。

本次先用离线缓存和真实 preview/native_frames 逻辑重放，结果为 0 帧及 visual:snapshot_index_unavailable。该响应当时缓存年龄约 9804.6 秒，仍在一天有效期内。再把刚取得的正常时间索引交给同一 native_frames 代码，实际生成 5 张预览图并查看拼图；旧空索引缓存未被替换。说明取图代码能工作，而一次缺字段响应能在本地持续影响后续预览。

本次空响应的 indexs 和 video_shots 同样为空，原报告建议的字段兜底在这些响应里无数据可用。匿名通道也出现过空索引，不能直接把“改匿名请求”当作已验证修复。

另外，Reader.preview 优先使用已有完整媒体的本地帧；因此本轮特意隔离重放原生 snapshot 分支。已经 open 过的视频能显示本地帧，并不能证明原生接口的旧缓存已恢复。

## C ASR：重复现象、拒绝阈值与证据边界

BV1Z8xA6zEpD 的原记录是 Whisper 在 0–120 秒得到 3 段。使用同一现有媒体、同一精确时间窗和实际组件解码函数，在隔离目录重新运行，耗时约 20.593 秒；文本、时间与置信指标全部复现，没有复用原语音结果，也没有改变原 manifest 或 review。

3 段共享 no_speech_probability=0.7382、avg_logprob=-0.6621；平均词概率分别为 0.0156、0.5929、0.0351。组件全部标记 low_word_confidence 与 suspect_decoding。

为何没有被上游自动丢弃，可以从已安装 faster-whisper 代码直接解释：默认 no_speech_threshold 为 0.6，但 avg_logprob 高于 -1.0 时仍保留候选。本例恰好满足保留分支。组件随后增加质量标记；reading 视图仍会传递这些 flags，review_status 仍为 pending。ready 表达识别处理已有输出，不表示内容已获语义验证。

这证实了“可疑候选会被返回”，没有证实“这些词一定不存在于音轨”。音量平稳不能区分口播、音乐与带人声的音乐，录屏中无人出镜也不能排除画外音。没有独立核听的真值，不能因低置信就删除所有此类候选，也不能推广为任何纯音乐视频都会输出虚构文字。

**原 Qwen 对照不能作为本例的独立无语音证据。** Whisper 的争议段在 0–120 秒，而 Qwen 用的是 300–360 秒。后者输入为 298–362.03 秒，原始解码文字长度 2，存在 1 个原始对齐单元；该单元时间为 298–298 秒，落在请求所有权区间之外。真实 owned_chunk 回放后，保留的单元为 0、text 为空，随后 qwen.decode 用“text 为空”写出 no_speech。这里至少存在对齐/归属过滤这一条解释路径，不能当成声学上确认整个视频没有人声。

## D 打开失败、图片和登录状态

两个历史任务确实失败。原始 error 分别为 yt-dlp 的 Unable to download webpage: read operation timed out 与 Remote end closed connection without response；已安装 BiliBiliIE 的第一步确实访问源网页。故障可以定位到网页获取的传输阶段。

但现有记录没有网络抓包、代理/TLS/DNS 对照或服务端日志，无法把责任具体定位为“B 站网页层重置当前出口 IP”。稍后同参数成功也只能说明该通路并非持续失败，不能证明版本、请求头或环境因素已全部排除。本轮未重复下载大视频，也没有为碰到一次失败反复重试。

open 的语义也需纠正。真实 _open 在来源就绪后调用 read，read 会抽帧并进入交付。BV1KLxN6ZERf 的初始交付快照共 9 页，原生图片在第 8 页；BV1QHxe6jEF9 共 16 页，图片在第 15 页；BV1Z8xA6zEpD 共 18 页，图片在第 17 页。页码均从 0 起。首包 image_bytes=0 只说明当页没有像素块，不能推导“open 不提供图”。沿 delivery.next_cursor 就能到达原生图页。

登录方面，本次受控 nav 请求确认 isLogin=true。源码的 _maintain 在账号验证通过后，仍可能因确认/续期接口不可用返回 authenticated=true、renewal=unavailable。用合成响应调用真实状态归并逻辑，得到 unavailable → not_needed，并验证 refresh=true 时进入 _renew 分支。没有触发真实账号续期，真实轮换能否成功仍待相应时机验证；现有状态既不能证明永久无法续期，也不能承诺未来续期必然成功。

最后，verifying_speech 是 OCR 与文字的机器对照；没有 review commit，不能叫作已完成人工或宿主语义校对。

## E 后续修复依据与本轮范围

优先处理的是成功响应的字段有效性和缓存策略：避免把缺时间轴的响应作为全天可用的预览材料反复命中，保留明确缺口，在原预算和风控边界内提供有界刷新或重取。恢复索引后再取图，不能捏造时间。

语音方面应分清原始候选、低置信/对齐不确定、无有效输出和经核实无人声。先为争议片段建立同一时间窗的独立听觉依据，再判断是否调整阈值、状态或消费提示。本轮没有安装新模型、自动换引擎或调用云端。

源码保持原提交 253c955；本轮仅完成排查、复现实验和问题登记。网络计数由 37 增至 54：14 次索引对照、1 次登录只读查询、2 张原生图集；限额仍为 120，未暂停、未提额。原坏索引缓存、原音视频和原识别/校对记录均保留。

## F 证据位置

证据索引见 summary.json。完整工作区原始响应在 independent-diagnosis-20261031/videoshot；离线索引为 offline-inventory.json；同窗口 ASR 与 Qwen 归属回放在 asr；预览恢复与续期语义回放在 followup.json。原始响应不含导出的 Cookie 或令牌，仍作为本地排查材料保留，不随公开摘要上传。
