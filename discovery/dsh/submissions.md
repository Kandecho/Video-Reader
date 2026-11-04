# 社区收录申请与资料

日期：2026-11-04。已按用户授权提交[开放插件市场 Issue #243](https://github.com/polang233/dsh-plugin-index/issues/243)及[Awesome DSH PR #12055](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/12055)，均待维护者处理，不能表述为已收录。PR 仅新增下述一个 YAML，自动检查仍在运行。作者索引已公开可订阅，社区收录须分别按对方流程处理。

## 开放插件市场

[收录表单](https://github.com/polang233/dsh-plugin-index/issues/new?template=plugin-add.yml)接受维护者确认的固定 Git 来源。可填写：

| 字段 | 内容 |
|---|---|
| 插件地址 | https://github.com/Kandecho/Video-Reader ，子目录 adapters/dsh |
| 名称与版本 | dsh-video-reader 0.1.0 |
| 固定提交 | f2656bf030ec94b9f6dfea22008c1d3168f4e4c6 |
| 简短说明 | 为 DSH 接入视频文字与原生画面、通用队列/历史，以及 Scroll 独立 B 站账号、收件与授权投递；复用现有 Windows 核心 |
| 许可证 | MIT；核心另保留第三方声明与模型许可 |
| 已验证环境 | Windows，本机 DSH 0.2.2-rc.1，核心 0.10.0rc6 |
| 安装与验证 | [DSH 指南](../../docs/dsh.md)、[薄包验证](https://github.com/Kandecho/Video-Reader/blob/main/validation/dsh-bundle-20261104/report-source.md) |

补充披露：薄包无安装脚本或捆绑运行环境；需预装核心并设置 VIDEO_READER_ROOT。平台登录与数据保留在核心目录；模型由宿主选择。索引、插件安装不会自动开启投递或新增调度。持续自动化仍在试用，常驻收件和持续后台阅读未实施。[能力状态](../../docs/capabilities.md)。

## awesome-dsh-plugin

依[贡献规则](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/blob/main/contributing.md)，可提交单一文件 `data/plugins/Kandecho__Video-Reader--adapters-dsh.yml`：

```yaml
url: https://github.com/Kandecho/Video-Reader/tree/main/adapters/dsh
name: Kandecho/Video-Reader#dsh-video-reader
category: tools
description:
  en: 'Connects DSH to timestamped video materials, shared queues/history and Scroll account workflows through an existing local installation.'
  zh: '复用现有本地安装，为 DSH 接入带时间的视频材料、通用队列/历史和 Scroll 账号工作流。'
```

该渠道支持 monorepo 子包，README 由条目生成，不应手工修改对方 README。公开、真实 bundle、许可证、维护与 topic 等条件已有对应材料；合并仍由对方维护者决定。

## Topic 发现型目录

[bruc3van/awesome-dsh-plugin](https://github.com/bruc3van/awesome-dsh-plugin/blob/main/CONTRIBUTING.md)会从公开仓库、dsh-plugin topic 和简介发现候选，再审核。我们已具备这些入口，但尚未据此确认进入其待审核队列或通过审核。自荐展示位有独立的星标要求，不能与普通发现和收录标准混为一谈。
