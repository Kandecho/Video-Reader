# 作品列表与分镜材料接口

身份：0.9.0 新材料接口的操作参考。通用阅读见 [reader-reference](reader-reference.md)，实现与保全证据见 [0.9.0 验收](../validation/material-0.9.0/report-source.md)。

## 评论、楼中楼与弹幕

0.10.0rc4 起，open/read 可用 `include_danmaku=True`（CLI `--include-danmaku`）组合弹幕，默认关闭。同区间字幕、画面和弹幕共用播放时间轴，保留字幕段 ID、邻近帧 ID 和实际时间差，并与原媒体 CID 绑定。材料游标负责冻结续读，获取失败不抹掉主材料。export 同名选项仅附带已获取快照，不联网。详见 [组合与续读契约](material-delivery.md)。

Reader 0.10.0rc3 新增 `video_comments` 和 `video_danmaku`，CLI 分别为 `comments` / `danmaku`，共用组件登录、账号缓存、请求限流与风控暂停。参数和续读规则见 [阅读 Skill](../skill/SKILL.md#comments-and-danmaku)。

评论每页 1–20 条，可按 newest / likes / replies 排序；`root` 指定根评论读取楼中楼。保留 ID、原文、作者、时间、点赞和父子关系，置顶单列，内嵌回复只是预览。评论跨视频分 P；平台 count 可能包含楼中楼，不能当根评论的准确数量。短页或重复会保留 partial / retry_page，并在有 next_page 时继续。平台动态删改也可能影响翻页。

2026-11-06 起返回 `reported_total_scope` 和 `end_reason`。楼中楼或平台分别报告根评/含回复数量时可按相应计数推尾（scoped_count_boundary）；口径未明时不据总数计算根评页数。无明确结束信号的空页返回 partial、empty_page_unconfirmed、retry_page，next_page=null 表示不自动推测下一页；可显式重查该页或指定后页，不能声称已取得全部评论。`pagination_end_confirmed` 区分平台明确结束/空集合与计数推断；collection_complete 仍不代表此前页或历史全量已读取。

弹幕按 URL 的 p 选择 CID，按平台分段元数据读取，返回源时间、正文、ID、模式和创建时间。每次交付 limit=100（1–200）；`next` 原样续读，同段的 snapshot_id 锁定已抓取内容，空段继续后续分段。`collection_complete` 仅说明当前调用本身交付完声明的集合；宿主需累计页/段并保留缺口。当前弹幕池不等于历史全量，BAS/特殊专包和互动弹幕本轮未纳入。

独立和对齐弹幕的获取/解析失败保留 `error.code/type/stage/next_action`，区分账号检查、来源元数据、弹幕元数据、分段请求与解析；原稳定错误码可回查。平台暂停、额度、登录、网络及坏响应分别提供后续动作，查询不自动恢复或换账号。可选弹幕失败仍保留语音、画面和成功分段。旧历史 danmaku_unavailable 快照不反推根因，需显式重取才能得到新诊断。

## UP 主原生作品分页

MCP `video_uploader_videos(source, page=1, offline=False)`；CLI：

```powershell
& 'D:\IA\apps\video-reader\run.ps1' uploader-videos 'BV1ptnb6uEES' --page 1
& 'D:\IA\apps\video-reader\run.ps1' uploader-videos 'https://space.bilibili.com/UID/video' --page 2
& 'D:\IA\apps\video-reader\run.ps1' uploader-videos 'UID' --page 2 --offline
```

UID 为正整数。空间链接支持 `/video` 与 `/upload/video`；BV 或视频链接先解析 owner.mid。一次只取一页，page 为 1–1000 范围内且不超过平台报告总页数的整数；采用平台原生页大小，目前为 30，不提供会造成漏项的任意 page-size。已读或已缓存作品仍列出，不将搜索筛选逻辑套到完整作品枚举。

| 字段 | 含义 |
|---|---|
| `uploader_id` / `uploader_url` | 稳定 UID 与空间链接；新搜索候选和新打开视频的元数据也保留 |
| `reported_total` / `total_pages` | 平台此时报告数量，不是永久快照 |
| `page_complete` | 本次页的条目数是否符合平台报告；同页去重另计 |
| `collection_complete` | 仅当第一页已包含全部唯一作品时为 true；最后一页不代表此前页均已取得 |
| `next_page` | 下一页；部分页返回本页号供调用者决定是否重试；完整末页为 null |
| `status` | ready / partial / blocked / failed；拒绝和缺项如实保留，不回退搜索 |
| `items` | video 或平台集合入口；集合不伪装成单个视频，内容尚未阅读 |

跨页遍历由宿主在用户请求范围内完成，并按 BV/集合 ID 去重、记录成功页与缺口。发布期间作品可能变动，分页不是事务快照。CLI 遇到非 ready 的列表或批量结果以退出码 1 提醒调用者，JSON 仍可读取。身份解析、参数或登录失败可能直接报错，不能将其解释为空列表。

复用锁定的 yt-dlp 2026.08.19 的 Bilibili 签名和分页，所有 JSON 请求仍经过共享 Platform：组件登录、账号域缓存、间隔、日请求额度与风控暂停。在线先维护和核验登录，离线不触发核验。当前 600 秒列表缓存、86400 秒材料缓存沿用现有配置；不另装下载器、不导出浏览器 Cookie。风控拒绝保留此前成功页，下一步应查登录及错误；不会自动恢复暂停状态。旧会话里的 owner 字段不做批量回填，需要时使用作品接口或在线 metadata。

## 独立预览与密度选择

| 入口 | 默认 | 可选控制 |
|---|---|---|
| `video_preview(source, ...)` / `preview SOURCE` | light，5 张，单图输出 | density=light/dense；max_frames=1–120；contact_sheet=False |
| `video_preview_batch(sources, ...)` / `preview-batch SOURCES...` | 1–10 条；light，5 张/条；每条拼图 | 同上；contact_sheet=True |

共同支持 offline=False、include_comments=False。密集模式默认 48 张；设置 max_frames 覆盖张数，不改变密度名称。原生分镜下载上限为 light 两张雪碧图、dense 八张，实际独立帧数可能少于请求数。默认保持轻量；风格、转场、幻灯片和分镜比较按任务选 dense，不把它设为所有阅读或日推的全局默认。

```powershell
& 'D:\IA\apps\video-reader\run.ps1' preview 'BV1ptnb6uEES'
& 'D:\IA\apps\video-reader\run.ps1' preview 'BV1ptnb6uEES' --density dense --max-frames 48 --contact-sheet
& 'D:\IA\apps\video-reader\run.ps1' preview-batch 'BV1ptnb6uEES' 'BV1v1HA6REgb' --density dense
```

Reader 优先复用同账号、同视频分 P 的完整媒体缓存及已有抽帧；缺少对应密度时只做本地抽帧，不运行 ASR/OCR 或重新下载。由此取得的 source_frame 保留精确源时间及 source_session_id。否则用平台原生分镜，precision 为 approximate_native_snapshot，时间为平台索引的近似值。保留黑场、纯色场景；仅合并同一原生格子，不按颜色判空。拼图每格有序号和源时间，标题标识 BV/P 与精度类型。

MCP 直接返回图片内容，CLI 返回绝对图片路径，宿主必须打开查看。批量按视频返回成功、部分或失败状态，单项失败保留其他项。默认拼图模式省略逐帧路径和长字幕，只给字幕类型、语言和段数；用相同参数单条 preview 获取完整字幕和帧明细。`--no-contact-sheet` 可恢复逐张输出。

预览字幕为未经校对的材料；已有修订正文仍通过 transcript/read/review 取回，原文及校对历史不覆盖。`visual_sampling` 报告请求数、返回数和精度，complete_continuous_coverage 始终 false。预览或元数据不等于整片读完。旧的 agent preview 兼容入口保留；普通 preview 不初始化 Scroll 状态，不改变日推策略。
