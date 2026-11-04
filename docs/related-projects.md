# 相关项目与不同侧重

日期：2026-11-04。这里列出可供用户选择和维护者参考的相关项目。链接表示比较与引用来源，不表示代码依赖、共同维护或质量背书；实际使用的第三方代码与许可另见 [THIRD_PARTY_NOTICES](../THIRD_PARTY_NOTICES.md)。

## 与 dsh-bili-scroll 的比较

[c1overzz/dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll) 同样围绕 B 站个人账号开展选片、报告和互动。下表的对方能力依据其作者文档，本批未安装验证；我们自己的状态见[能力说明](capabilities.md)。不把两边的声明当作同等验收证据，也不比较未测的速度或稳定性。

| 侧重 | Video Reader + Scroll | dsh-bili-scroll 作者文档所述 |
|---|---|---|
| 使用入口 | 通用视频阅读、独立队列/历史、个人 B 站工作流整包提供；可只使用其中一部分 | 以 DSH 内的每日 B 站选片、报告和互动为中心 |
| 平台账号 | 组件单独扫码登录小号，使用小号首页，与主号授权私信；已有真实使用 | 提供自己的扫码登录与本地凭据，支持私信及其它互动配置；账号独立不是我们独有的设计 |
| 收件与记录 | 主号来信显式同步；旧消息为历史，新视频按界线入队；附言、任务与结果可追溯 | 提供私信双向、已刷视频列表、筛选和逐片笔记；未据 README 判断其通用队列模块是否独立 |
| 读取与分工 | Reader 取得材料；宿主理解；`reading_tasks` 管任务；Scroll 管个人账号工作流。两套 MCP 共享核心 | 内置 B 站 MCP，配合 headless 任务及专用 profile；字幕优先，支持画面和可选本地转写 |
| 投递与自动化 | 有授权私信发送、入队/分流/结果汇报；本机每日首条工作流仍在试用 | 描述私信、评论 @、收藏和峰谷定时等选项，包含默认关闭的互动开关 |
| 界面与宿主 | 当前不做专门前端；提供 Codex、Claude 和 DSH 薄适配 | 提供 DSH 设置面板、列表及操作入口，强调 DSH 内使用 |

对方这份说明固定于 [f883d79](https://github.com/c1overzz/dsh-bili-scroll/blob/f883d79fa536a2d1610dbb89796e6f48266103d7/README.md)。我们与它的主要差别是阅读组件和通用任务的复用方式，以及产品入口；不能据此宣称功能整体更完整或更稳定。

## 其它值得参考的入口

- [vlln/dsh-video2text](https://github.com/vlln/dsh-video2text)：侧栏视频转文案、播放器和逐字稿；短演示、界面截图及首次使用确认方式值得参考。
- [Aurum807/dsh-bilibili-video-summary](https://github.com/Aurum807/dsh-bilibili-video-summary)：聚焦发链接后总结，先展示对话体验，再说明安装、自检与限制。

更完整的仓库呈现、包元数据及实际分发核对在[本批考察](https://github.com/Kandecho/Video-Reader/blob/main/research/dsh-presentation-20261104/report-source.md)。这些项目与我们的包不互相安装，也不共享凭据或运行目录。
