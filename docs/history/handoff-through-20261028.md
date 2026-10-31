# 历史快照：2026-10-29 整理前

身份：保留当时全文与证据链接；其中“当前”“下一步”和授权状态仅适用于当时。现行目标、状态及后续方向从 [当前知识路由](../registry.md) 读取。相对链接已按归档位置调整。

---

# Video Reader 跨会话交接

身份：2026-10-28 整轮实现后的快照。目标与当前边界在[路线](../../planning/roadmap-20261021-source.md)，整轮证据见[rc1 验收](../../validation/reader-0.10.0rc1/report-source.md)，最新修复与 213 项回归见[rc2 验收](../../validation/reader-0.10.0rc2/report-source.md)。

共享核心 0.10.0rc2、薄插件 0.5.1，Reader 16 个工具、Scroll 3 个工具。已实现任务选图、无损分页与绑定来源/修订的持久续读、原图裁切、增量语音、基础声音、手动 YouTube 状态、显式版本导出、可变路径候选，以及 Scroll 确认式批量续读。rc2 的 213 项回归通过；rc1 的真实批次 51 页/2445 段与已有正文完全一致。这证明传输和重放，该历史批次不证明语义理解；本轮另补两片实质比较，见下方最新记录。已交付不意味着宿主读懂或校对完成。

运行目录仍为 D:/IA/apps/video-reader；源码、配置、模型、凭据、缓存和旧校对没有整目录替换。两批安装备份与保全哈希分别见 validation/reader-0.10.0rc1/install.json 和 validation/reader-0.10.0rc2/install.json。新聊天/重连 MCP 加载新工具与技能；已有连接的旧工具列表不代表磁盘安装失败。

可移植导出案例：BV1nGJ26JEuh，session v_67f60950efb89868ad54bb9c，captions snapshot 78e3a89218c75c2697ba6a66 revision 1，367 段、25 修正、3 疑点、86 图。选择显式 revision 1，不误用早期 revision 0。统一 export 已修复旧输出缺陷；不自动改写历史缓存路径。

## YouTube Cookie 接续（2026-10-28）

当前能力口径：支持导入用户导出的短期 Cookie，在其有效期内限时访问；长期登录态维持暂缺。成功检查与重启后仍有效只证明当次状态，不证明具备维持长期登录的能力。有效期由平台决定，失效后用户重新导出并替换。

正式配置 platforms.youtube.cookies_file 指向 C:/Users/USER/Documents/Codex/2026-10-26/bv1v1ha6regb-bilibili/.private/youtube/cookies.txt。只用于本机，不写入候选包。文件原文不得输出。服务器登录检查、实际下载和字幕通过；文件哈希未改写。不承诺永久有效。旧 cookie-ytb.txt 已失效，不应误选。失效后请用户更新手动文件，离线材料继续可读。

## 后续边界

本轮 Reader 功能实现与 Scroll 首轮批量调试已完成；下述真实任务暴露的两项缺口已在 rc2 修复。公开建仓/上传/许可证尚未决定；轻量标签、自主探索、长期推荐收益不属于本轮实现。保持首页首条日试用与现有投递规则，见[daily-trial](../daily-trial.md)；不要为验收重跑发送或另建触发器。

Qwen 可配置独立 runtime_dir；本机仍保留原 research/asr-engine-20261021/.venv 与原模型/配置，不删除。新的干净安装默认 runtimes/qwen，具体依赖见[安装说明](../installation.md)。Claude 本轮只接收自制样本；真实用户视频由 Codex 及本地组件验收，不能混淆证据范围。

## 3Blue1Brown 首轮局部读取（2026-10-28 历史）

用户要求直接从 B 站检索到读取，已完成：搜索“3Blue1Brown 傅里叶变换”→官方 BV1pW411J7s8→session v_1ed890055a512d73746d7ec3。720p、1256.23 秒；全片仅做 24 帧概览，重点读 780–1040 秒，不是全片精读。无软字幕轨，本地 Whisper 分三次处理任务区间，61 段全部交付并读取；另有 0–120 秒开头草稿。

当时长连接仍为旧 MCP，该次读取改用正式 0.10.0rc1 CLI，共用媒体和会话。12 张 adaptive 图分 8+4 跨进程续读；10 张精确补帧和一处原像素裁切核对公式过渡与漏句；固定页 ac32881011d84199acc40b1d:0 在语音变化后仍与原页相同。旧 :next 在语音身份变化后明确拒绝，不混合版本。

rc1 基线在 1019.650–1028.780 秒间漏了讲解，但 processed 显示完成。复听 job e9884c6ae1b0404aba78cc66（1014–1035 秒，无提示、本地 Whisper）与 1021/1024/1027 秒烧录字幕共同补证；没有重写基线。rc1 当时仍要求全片转写才能校对，未标成已校对；历史证据见 [summary](../../validation/reader-0.10.0rc1/3b1b-20261028/summary.json)。

## rc2 修复接续

同一 1018–1042 秒音频的四组对照：去掉隐式中文标题提示恢复漏句；只关闭 VAD 或 hallucination_silence_threshold 未恢复。新 Whisper 默认不再用标题，显式 context 保留。旧标题提示 profile e54a92b0580da2d4f3b85af3 和原始记录未改，新无提示结果独立保存。默认先找无提示轨，否则复用旧缓存；显式传原标题可重开旧轨。

该例无提示重读 780–1040 秒共 65 段，逐页实际读取并提交局部 revision 1，校对文档 2855ff1b660d0c35f2d9cbdc。首尾请求边界截句保留两条备注；scope_review.complete=true，review.complete=false。prepare/commit/status 的可选 start/end 已同步 CLI/MCP/Skill，提交带原样 review_scope，继续补读保留旧审阅。原文指纹与稳定校对文档分别绑定，旧游标不混用变化后的材料。当前长连接可能仍需新连接加载参数，CLI 直接生效。

修复记录、保全清单及候选入口见 [0.10.0rc2 验收](../../validation/reader-0.10.0rc2/report-source.md)。路线 HTML 随本次源稿重建。

## 文档整理后接续

2026-10-28 已更新 README、路由、操作参考、日试用快照和路线阅读版。F 节现在只解释建议的下一步、按实际失败加强及后置新增；原详细实施契约另存 planning/roadmap-20261028-implemented.md。本次没有新增开发任务或调度。

该建议现已执行完 Reader 三类任务与 Scroll 两片比较；独立聊天理解和人工质量复核仍待用户体验。2445 段历史传输一致不能替代本轮具体阅读成果。反馈存储已有；标签和探索为后置候选。当前候选路径与文件校验见 validation/docs-20261028/summary.json，旧候选及验收保留。

只读查看了日记录：10/24–28 均 finished 且 accepted_not_receipt_verified；10/28 20:00 的任务在 20:02:21 退出 0。实际收件与长期偏好收益仍未知。没有为本次检查触发任务、发送或读取私信。

## 最新：真实任务与 Scroll 实质比较已完成

用户授权“自行完成1，随后进行2；用户提供人工复核和体验”。本轮三类 Reader 阅读完成，再完成 Scroll 两片实质比较。成果见 validation/task-reading-20261028/report-source.md 与 report.html；summary.json记录范围；resume-check.md可供另一个聊天接续。不要重复从头转写。

3b1b v_1ed890055a512d73746d7ec3，asr/context空，289段全部已读；2855ff1b660d0c35f2d9cbdc rev2，4修正、0未决，保留rev1历史。MAW v_dc2721f3e01115bcd77a3eea，captions，222段；ec84c670787b650212415bda rev1，7修正，82秒背景混音1疑点。长YouTube v_152006cb4021a3f1a2d7100b，captions en-orig，1903段；e99f55bcba484e2b82ed8fee rev1，3个重叠条目恢复同一句否定，文件名1疑点。不要把完成审阅当逐字真值。

新Cookie由用户另给随机文件名，已导入同一私有路径、保留原件。在线及两个新MCP进程的检查均logged_in。无需再次索要固定文件名；仍按过期手动替换。此为短期凭据限时访问，不计为长期登录态维持通过。fresh-mcp-result.json验证冻结页、续页ID与修订、旧next拒绝；没有声称跨聊天语义验收已通过。

Scroll batch_d86402ff43834769b72bc870240dc56e：MAW与v_d138ef2a6f645451c30be582（BV1z9n86gEWS），10页均观察再确认；两片delivered、无失败、0发送、未改调度。结论保留短片02:39“默认/初稿可能是真需求”，并指出42%旁白与截图口径不一致。短片72段review rev1，7修正、1疑点。不得把测试选片或Agent评价写成用户偏好。

新增待办：可追溯连续字幕阅读视图。YouTube1903条中950条约10ms、104458字符；滚动重复和Scroll开头重复增加成本，原文完整。后续减少重复展示必须保留时间、原始段ID与修订关系。本轮没改生产代码，不扩展为另一阅读实现。正式路线F节已更新；源码候选保持上一版，未发布。人工复核待用户反馈。
