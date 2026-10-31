---
title: Video Reader 更新已实施
subtitle: 2026-10-26 · 核心 0.9.0 · Codex / Claude 插件 0.4.0
template: doc
theme: inkread
lang: zh
---

已补上 UP 主原生作品分页、独立 Reader 预览，以及可选密集批量分镜。两端插件已实际安装、调用并查看图片。原有阅读、语音、校对和 Scroll 能力保留。

## A 新能力与默认策略

| 能力 | 默认行为 | 按任务选择 |
|---|---|---|
| UP 主作品 | UID、空间链接或 BV；一次一个原生页，目前 30 条 | 按 next_page 继续；显示总数、页完整性及失败状态 |
| 单条预览 | 5 张图；优先已有完整视频缓存 | dense 默认 48 张，max_frames 可设 1–120；可输出拼图 |
| 批量预览 | 1–10 条；每条轻预览与一张拼图 | 风格、剪辑、幻灯片或分镜比较可选 dense |
| 接口 | CLI 与 MCP 调用同一 Reader 门面 | 现有 agent preview 兼容入口保留 |

密集分镜是正式支持、按任务启用的能力。普通视频与日试用仍走原有轻量默认。原生分镜标明近似时间；完整缓存抽帧保留源时间。拼图标注 BV、分 P、格子序号与时间，不按颜色丢弃黑场或纯色画面。

批量结果保留单项失败，默认省略长字幕与逐帧明细；需要时单条展开。预览仍标为 previewed_not_read，抽样不代表连续动作覆盖。

## B 拒绝原因与修复方式

本机锁定的 yt-dlp 已有 B 站 UP 主列表功能。此前命令没有接入组件现有登录。相同签名查询及请求头的对照中，匿名返回 -352，使用组件登录返回 0。

新接口复用现有登录维护、身份核验和 yt-dlp 签名分页；请求经过共享缓存、限额、间隔与风控暂停。没有升级下载器或另建一套凭据。

| 真实检查 | 结果 |
|---|---|
| CoCoVii，UID 9142182 | 平台报告 221 条 |
| 第 1 / 2 页 | 各 30 条；两页无重复；next_page 分别为 2 / 3 |
| 离线复用第 2 页 | 命中相同列表缓存 |
| 完整性 | 两页 page_complete=true，collection_complete=false |

最后一页不代表此前页都已获取。失败如实返回 blocked / partial / failed，保留成功页，不以搜索结果伪装完整列表，也不自动解除风控暂停。

## C 已有能力的保全

| 验证 | 证据与范围 |
|---|---|
| 回归测试 | 原有 169 项加 16 项新测试，共 185 项通过 |
| 兼容接口 | 旧阅读、转写、校对、复听参数保留；新参数为追加可选项 |
| 安装保护 | 23 个目标文件替换；安装前后 123 个受保护文件哈希相同 |
| 实际调用后 | 75 个配置、Scroll 业务、旧会话及校对文件继续保持原哈希 |
| 旧校对正文 | revision 1；367 段已审阅、25 段修正、3 处疑点保持可读 |
| 依赖与资源 | yt-dlp 仍为 2026.08.19；未升级运行依赖、搬移模型或替换配置 |

本地密集预览按需追加了一个 48 帧读取记录；原语音与校对不覆盖。共享取数缓存和网络计数随正常调用更新，不属于 Scroll 业务状态。没有修改 Windows 日推任务，也没有发送消息。Whisper、Qwen 的既有分支经过回归覆盖，本轮未额外重跑全量模型解码。

原文件备份位于 `D:/IA/apps/video-reader/validation/material-0.9.0/backup`；安装清单包含旧、新哈希。生成插件也有备份，未直接手改宿主缓存。

## D 两端同步与实际验收

| 层 | 当前状态 |
|---|---|
| 核心与包元数据 | 均为 0.9.0 |
| Reader / Scroll MCP | 11 / 2 个工具，保持分工 |
| canonical Skill 与文档 | 已更新；50 条 CLI 示例全部可解析 |
| 两端薄插件 | 0.4.0，每端 5 文件；已安装内容与生成目录完全一致 |
| Claude 格式检查 | 插件与 marketplace 通过 strict 校验；尚未准备公共商店许可及图标材料 |
| 新宿主会话 | Codex、Claude 各实际调用两项新工具；离线取得 30 条列表、2 张 48 格拼图并识别画面区别 |

宿主验证覆盖本轮材料获取与图片显示，不代表重新完成整片语义阅读。旧会话可继续使用已加载工具；新会话加载新工具与 Skill，无需为此次更新重启电脑。

## E 立即使用

可以直接说“列出这个 UP 主的视频”“密集预览这两条视频，比较分镜”。CLI 也可以独立运行：

```powershell
& 'D:\IA\apps\video-reader\run.ps1' uploader-videos 'BV1ptnb6uEES' --page 1
& 'D:\IA\apps\video-reader\run.ps1' preview 'BV1ptnb6uEES'
& 'D:\IA\apps\video-reader\run.ps1' preview-batch 'BV1ptnb6uEES' 'BV1hnnc6gE1x' --density dense
```

详细参数见[材料接口](D:/IA/apps/video-reader/docs/material-reference.md)。结构化结果、测试日志和安装记录归档在 `D:/IA/apps/video-reader/validation/material-0.9.0/`。

本轮保留了已登记的统一导出、可移植图文交付等后续缺口；没有把它们混入这次更新。插件缓存与更新机制参考 [OpenAI 官方插件文档](https://developers.openai.com/plugins/build/plugins)，实际安装以本机 CLI 和新会话结果为证。
