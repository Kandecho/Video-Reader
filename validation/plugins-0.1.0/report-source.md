---
title: Video Reader 薄插件已安装
subtitle: 插件 0.1.0 · 核心保持 0.6.2 · 一份核心与数据，两个宿主适配
template: doc
theme: paper
lang: zh
---

## A Codex 已安装，其他会话这样用

本机已安装并启用 `video-reader@video-reader-local`。

新开一个 Codex 会话，直接说：

> 用 Video Reader 读取这个视频：链接或 BV。读完后我们再讨论。

要明确指定阅读技能，可先选择 `$video-reader:video-read`。

不需要再读开发 handoff 或重新扫码。若当前桌面应用尚未刷新，重启 Codex 后再新开会话。

## B 真正验过什么

| 检查 | 结果 |
|---|---|
| 本机 Codex 安装状态 | installed、enabled |
| Codex 原生技能发现 | video-reader:video-read 可见 |
| Codex MCP 工具 | 同一连接中发现八个工具 |
| 实际调用 | 字幕、取帧、校对状态均返回 |
| 图片 | 收到原生图片块，已打开检查 |
| 回归测试 | 115 项通过，含 7 项新打包测试 |
| Claude Code | 插件与本地来源校验通过；未安装 |

验证使用临时 Codex 运行上下文，没有创建持久聊天。没有发送模型推理请求或重跑 ASR。这证明宿主接入可用，不冒充新一轮完整视频理解验收。

## C 不重复复制，仍共用 D 盘这一份

每端包只有 4 个文件，约 15KB。Codex 缓存仅包含清单、MCP 配置、阅读 Skill 和短说明。

| 内容 | 保存与复用方式 |
|---|---|
| 核心、Python 环境与模型 | 仍用 D:\IA\apps\video-reader 原安装 |
| 登录态、视频与校对缓存 | 两端指向同一个 config.json，不打进插件 |
| 阅读流程 | 一份 Skill 源稿，构建时同步两端 |
| 当前默认策略 | 字幕优先，Whisper 不变；Qwen 显式可选 |

实测原始语音、核心配置和登录文件未变。取帧仍写入 D 盘共享缓存。

共用的是磁盘安装和数据，不是单个内存推理进程。多个会话使用 Qwen 时先错峰，不为此添加后台 GPU 服务。

## D Claude Code 的后续安装入口

Claude 适配已生成，本轮没有修改 Claude 用户设置。需要时运行：

```powershell
claude plugin marketplace add 'D:\IA\apps\video-reader\integrations\claude'
claude plugin install 'video-reader@video-reader-local' --scope user
```

安装后可用 `/video-reader:video-read`，或自然语言指定 Video Reader。

插件只面向本机 Windows，未作公开商店发布。维护时修改唯一 Skill 源稿，更新插件版本后重新构建和安装，不直接修改宿主缓存。
