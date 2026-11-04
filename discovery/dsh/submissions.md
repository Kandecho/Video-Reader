# 社区收录申请与资料

更新：2026-11-05。两条申请的状态分别核对，不把 Issue 关闭等同于拒绝，也不把检查通过等同于 PR 合并。

| 渠道 | 当前结果 | 可回查证据 |
|---|---|---|
| 开放插件市场 | **已收录** dsh-video-reader 0.1.0；Issue 于北京时间 11 月 5 日 00:46:02 以 completed 关闭 | [Issue #243](https://github.com/polang233/dsh-plugin-index/issues/243)、[维护者确认](https://github.com/polang233/dsh-plugin-index/issues/243#issuecomment-6636422560)、[市场详情](https://dshopen.org/zh/plugins/dsh-video-reader/) |
| Awesome DSH | **已合并收录**；北京时间 11 月 5 日 01:26:10 合并，PR check 成功 | [PR #12055](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/12055)、[主分支条目](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/blob/18fdd9b4d69a506a3b4519742113574785a2fc78/data/plugins/Kandecho__Video-Reader--adapters-dsh.yml) |

已从正式线上索引 `https://dshopen.org/index.json` 查到本项目：版本 0.1.0，固定提交 f2656bf030ec94b9f6dfea22008c1d3168f4e4c6，子目录 adapters/dsh，与原发布及实装来源一致。可在 DSH 添加这个社区索引源后搜索 `dsh-video-reader`；先准备核心与 VIDEO_READER_ROOT。回查范围和来源见[收录确认](../../validation/dsh-community-20261105/report-source.md)。

## 开放插件市场

[收录表单](https://github.com/polang233/dsh-plugin-index/issues/new?template=plugin-add.yml)接受维护者确认的固定 Git 来源。本次已获收录，保留原申请字段供维护回查：

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

依[贡献规则](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/blob/main/contributing.md)，PR #12055 仅提交文件 `data/plugins/Kandecho__Video-Reader--adapters-dsh.yml`：

```yaml
url: https://github.com/Kandecho/Video-Reader/tree/main/adapters/dsh
name: Kandecho/Video-Reader#dsh-video-reader
category: tools
description:
  en: 'Connects DSH to timestamped video materials, shared queues/history and Scroll account workflows through an existing local installation.'
  zh: '复用现有本地安装，为 DSH 接入带时间的视频材料、通用队列/历史和 Scroll 账号工作流。'
```

该渠道支持 monorepo 子包，README 由条目生成，不应手工修改对方 README。PR 已由维护者合并，提交为 18fdd9b4d69a506a3b4519742113574785a2fc78；目录源中的名称、仓库子目录及中英文描述与本次提交一致。

## Topic 发现型目录

[bruc3van/awesome-dsh-plugin](https://github.com/bruc3van/awesome-dsh-plugin/blob/main/CONTRIBUTING.md)会从公开仓库、dsh-plugin topic 和简介发现候选，再审核。我们已具备这些入口，但尚未据此确认进入其待审核队列或通过审核。自荐展示位有独立的星标要求，不能与普通发现和收录标准混为一谈。
