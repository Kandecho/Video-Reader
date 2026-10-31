# 诊断：preview 无画面、open 间歇失败与 ASR 幻觉

日期：2026-10-31
组件：`D:/IA/apps/video-reader`（yt-dlp 2026.08.19）
样本：
- `BV1KLxN6ZERf`（伊莉丝Lys，929s，cid 43165682580）
- `BV1QHxe6jEF9`（李好帅步履不停，1162s）复测
- `BV1Z8xA6zEpD`（Cyletix，888s，P1）复测
账号标记：`ACCOUNT_SCOPE`

---

## 一、结论摘要

| 现象 | 根因 | 性质 |
|---|---|---|
| `open` 前两次失败 | B站网页层对当前出口 IP 的间歇性连接重置 | 外部抖动，重试可过 |
| `preview` 返回 0 帧 | `player/videoshot` 在**带登录态**时返回空 `index` 数组 | 组件缺陷，可修 |
| 登录态 | 有效，但 `renewal=unavailable`，无法自动续期 | 隐患，非故障 |
| 无口播视频返回 3 段英文 | faster-whisper 在 `no_speech` 情况下输出幻觉，标记了 `suspect_decoding` 仍当作有效语段返回 | 组件缺陷，风险最高 |
| `open` 返回 `image_bytes: 0` | 设计如此，`open` 只落材料，画面需单独 `read` | 非缺陷，易误读 |

四类现象互不相关。

---

## 二、open 失败：网络抖动

三次对照：

| 时间 | 操作 | 结果 | 耗时 |
|---|---|---|---|
| 14:27 | 组件 open（job `j_be47f553c2404af19b36a8bf`） | 失败，`read operation timed out` | 41.7s |
| 14:29 | 组件 open（job `j_ba0f6f28f9d544cc92942eb3`） | 失败，`Remote end closed connection without response` | 24.2s |
| 14:32 | 手动 yt-dlp，参数同 `sources.ytdlp_base` | 成功，完整 info + 1080/720/480 格式表 | — |
| 14:33 | 组件 open（job `j_61c232c410584328b48d5e15`） | 成功，`acquiring_source` 11.2s，全流程 132.4s | — |

失败均发生在 `acquiring_source`，即 yt-dlp 抓 `www.bilibili.com/video/<bvid>` 网页这一步。
同一时刻 `Invoke-WebRequest` 抓同一网页返回 200 / 234742 字节。

排除项：cookie 失效（status authenticated）、yt-dlp 版本不兼容（手动成功）、参数错误（同一组参数成功）。
未定项：重置的具体触发条件。不编原因，只记录它可重试。

补充：本视频 yt-dlp 侧 `subtitles` 为空对象。字幕来自 B站 `player/wbi/v2` 独立链路，
共 487 段，0.7s 至 919s 连续覆盖。字幕与媒体下载两条通路互不影响。

---

## 三、preview 无画面：登录态导致 videoshot 返回空 index

### 现象

`data/preview/ACCOUNT_SCOPE/BV1KLxN6ZERf-p1/preview.json`：
`gaps: ["visual:snapshot_index_unavailable"]`，`frames: []`，`image_bytes: 0`。

### 对照实验

同一 URL（`/x/player/videoshot?bvid=…&cid=…&index=1`）、同一 UA、同一 Referer，
唯一变量为 cookie：

```
带组件 cookie   → code=0, index=0 项,   image=2 张
不带 cookie     → code=0, index=156 项, image=2 张
```

缓存文件 `3f09f8c953b134aabf6bc3d253766118d4e9c0c5d813220e7fd0acf3486a0c23.json`
保留了失败当时的原始响应：`"index": []`、`"indexs": {}`、`"video_shots": {}`，
而 `image` 两张雪碧图与 `img_x_len=10 / img_y_len=10 / 480x270` 网格参数均正常。

### 链路

`video_reader/preview.py`

1. `preview()` 调 `platform.json('/x/player/videoshot', {...})`，`platform.request` 带 cookie。
2. `snapshot_positions()`：`indices = snapshot.get('index') or []`，空即抛
   `PlatformError('snapshot_index_unavailable')`。
3. `preview()` 捕获后记入 `gaps`，`frames` 保持空，`image_bytes` 为 0。

判空行为本身正当：无时间轴则无法确认每帧对应秒数，fail-closed 优于给错时间。
缺陷在于它没有区分「接口没给」与「登录态让它不给」。

### 影响面

在登录态下，`preview` 的轻量预览对任何视频都拿不到画面。
`open` 成功后的本地帧（ffmpeg 抽取，本次 11 张）不受影响，
`preview` 优先复用 `source_frame`，故「open 过就有画面」并非偶然。

### 可选修法

1. `videoshot` 请求改用不带 cookie 的通道（对照实验已证明匿名请求正常）。
2. 或保留 cookie 请求，空 `index` 时用 `indexs` / `video_shots` 兜底，再不行降级为匿名重试一次。
3. 无论哪种，`gaps` 应区分 `snapshot_index_withheld_by_login` 与 `snapshot_index_absent`。

修改需落在组件源码，未执行。

---

## 四、ASR 幻觉：无口播视频被识别成英文

### 现象

`BV1Z8xA6zEpD`（CyIME 输入法，888s）无原生字幕，自动走本地 ASR：

```
language: en, probability 0.679
0–120s   → 3 段：nobody / i can't see you / really
300–420s → 0 段
```

三段均带 `low_word_confidence` 与 `suspect_decoding`。

### 排查路径

1. **先怀疑语言误判**。中文视频被判成 en，表面看像解码语言选错。
2. **音频电平**：0–300s 全程 RMS −19 至 −21 dBFS，无起落；600–860s 共 261 个窗口，
   仅 4 个静音，电平平稳如直线。这是背景音乐，不是人声。
3. **换引擎验证**：`--source qwen` 重跑 300–360s，返回 `no_speech`，0 段。
4. **画面**：手机录屏，黑底白字，内容为词库、布局、符号、表情、编辑与快捷键，
   底部有烧字幕。全片无出镜人声。

### 结论

视频确实没有口播，`no_speech` 是正确判断。那三段英文是从 BGM 片段里「听」出来的幻觉，
属 Whisper 在 VAD 残留片段上的已知行为。

组件给它打了 `suspect_decoding`，说明检测到了异常，但没有拒绝输出。
下游若不读 flag，会把它们当成内容。

### 影响面

任何纯音乐或无人声视频都会得到几段语法合法、内容虚构的「语音」。
这类错误比直接报错更危险，因为它看起来完全正常。

### 附带发现

Qwen 首次解码 60 秒音频耗时约 250 秒才返回 `no_speech`。心跳正常，不是死锁，
是模型加载与推理开销。「换一个引擎复核」这个动作因此很贵。

---

## 五、多接口复测：BV1QHxe6jEF9 与 BV1Z8xA6zEpD

| 项目 | BV1QHxe6jEF9 | BV1Z8xA6zEpD |
|---|---|---|
| `open` | 成功，154.4s | 成功，80.5s |
| 原生字幕 | 509 段 | 0 段 |
| 抽帧（材料层） | 11 张 | 12 张 |
| `read` 画面 | 3 张，170644 字节 | 有帧 |
| 评论 | 182 条，分页完整 | 408 条，分页完整 |
| 弹幕 | 54 条，0.58–352.691s | 3 条 |
| `error` | 无 | 无 |

弹幕 `progress_ms` 54 条互不相同（580–352691），时间轴正常，未出现全零。
评论字段（`id` / `root_id` / `parent_id` / `author` / `created_at` / `pictures` / `reply_preview`）
完整，`replies_complete` 与 `replies_hint` 正确表达了线程截断。

`open` 返回 `image_bytes: 0` 是设计行为：它只落材料，画面由 `read` 单独抽取。
两条 open 都返回 0，材料层实际有 11 张与 12 张，容易误判为画面缺失。

---

## 六、登录态

`login status` 返回：

```
authenticated: true
account_marker: ACCOUNT_SCOPE
verified_at: 1793428356
renewal: "unavailable"
renewal_code: "BILIBILI_AUTH_UNAVAILABLE"
```

凭据当前有效。不能自动续期，到期或被平台吊销即掉为未登录，需重新走扫码登录。
属已知设计取舍（组件文档亦注明凭据独立于日常浏览器会话）。

---

## 七、遗留

- `BV1KLxN6ZERf` 的 11 张帧已逐张查看；`BV1QHxe6jEF9`、`BV1Z8xA6zEpD` 只抽查。
- 语音校对（`verifying_speech`）已完成，均未做人工复核 commit。
- preview 缺陷未修。
- ASR 幻觉未处理。可选方向：无语音时拒绝输出；或改走 OCR / 画面路径。
- `BV1Z8xA6zEpD` 内容全在烧字幕里，语音路径读不到，需 OCR 层才可读。
