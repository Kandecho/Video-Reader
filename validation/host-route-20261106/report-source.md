---
title: 后台模型为什么反复失败
subtitle: 2026-11-06 · 已定位并修复 Windows 系统代理继承遗漏
template: doc
theme: paper
lang: zh
---

后台接入代码漏了 Windows 系统代理的继承。视频材料已经准备好，但新启动的 Codex CLI 无法正常取得工作区路由，因而没有返回阅读结果。此前的重试只重复了同一套启动环境，调短间隔没有解决根因。

## A 故障发生在哪里

```flow LR
定时脚本 -> Reader 材料
Reader 材料 -> 独立 Codex CLI
独立 Codex CLI -> 工作区路由
工作区路由 -> 模型
+ Windows 系统代理 -> 独立 Codex CLI: 已补齐子进程继承
```

后台不是在当前聊天里直接继续回答，而是启动独立的 CLI 进程。它复用已有登录，但仍要自己建立网络连接。官方文档也说明 codex exec 默认复用保存的 CLI 身份。[OpenAI Docs：自动化中的身份验证](https://learn.chatgpt.com/docs/non-interactive-mode#authenticate-in-automation)

三条任务共留下 7 次失败尝试：5 次请求超时，2 次最终报告 workspace routing discovery failed。日志显示切换到 HTTPS 后仍失败，没有产生 response.json 或实际笔记。CLI 当时有已保存的 ChatGPT 登录；日志没有额度不足错误。

## B 怎样确认根因

机器已有 Windows 系统代理，Python 网络访问能够使用它；启动环境没有 HTTP_PROXY / HTTPS_PROXY。只改变诊断子进程的代理环境，对同一 CLI、登录、模型与最小 JSON 请求作对照：

| 条件 | 实际结果 |
|---|---|
| 原启动环境，不显式传系统代理 | 45.766 秒超时 |
| 仅把现有系统代理传给 CLI 子进程 | 7.328 秒正常返回 |
| 修复后的原入口，实际图片及结构化输出 | 18.157 秒返回正确图片标题 |

这把问题定位到后台 CLI 的联网配置。诊断和修复都没有更换模型、账号、登录方式或系统代理。

## C 修复与验证范围

共享宿主入口现在会在 Windows 下读取已启用的系统代理，并仅传入 CLI 子进程。显式配置的代理（包括空值）优先，已有 NO_PROXY 保留，父进程与系统配置不改。工作区路由错误也按传输错误归类，适用既定有限重试。

新增 5 项代理与错误分类检查、原宿主 17 项检查通过，独立代码复核未发现重要问题。真实图片调用已成功；后续新任务仍按既定时段、资源、预算和重试上限运行。本次未重跑三条已经完成的任务，也没有据单次调用宣称长期运行稳定。

实现：[共享宿主入口](../../video_reader/host_runtime.py)。具体调用日志、对照结果与检查记录保存在 data/stage6-validation-20261106/host-route-diagnosis 和 .test-work/host-proxy-*.log。
