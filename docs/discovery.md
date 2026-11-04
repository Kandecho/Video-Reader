# 在插件索引中找到本项目

Video Reader 的 GitHub 仓库、DSH 索引和通用 MCP 目录是不同的发现入口。这个项目按整包提供 Reader、独立队列/历史和 Scroll；可用与试用范围见[能力状态](capabilities.md)。

## DSH：订阅项目索引

当前 DSH 不内置统一索引源。启用「插件 → 实验性插件 → 自定义插件索引」，再到「发现 → 添加索引源」填写：

```text
https://raw.githubusercontent.com/Kandecho/Video-Reader/main/discovery/dsh/index.json
```

这是项目作者维护的索引，包含可安装的 `dsh-video-reader` 版本及仓库入口。索引通过 HTTPS 直接返回 JSON，不依赖 Release 附件的下载重定向。支持 `plugin_market` 的模式可以先列出配置的索引，再搜索 `video reader`、`字幕 画面`、`账号 私信` 等短词组合。整句自然语言需求适合交给 Agent 拆成检索词。

索引中的安装来源是固定 Git 提交和子目录；[Release tgz](dsh.md)另供直接安装。请先准备 Windows 核心并设置 `VIDEO_READER_ROOT`。发现条目不等于已经准备好 Python、模型或平台登录。

## 社区收录不等于自行托管索引

项目索引可以立即供愿意订阅它的 DSH 使用，但不会自动加入别人已经配置的社区源。以下规则来自各项目的贡献指南，并非 DSH 官方统一审核：

| 入口 | 当前收录方式 | 本项目需要提供什么 |
|---|---|---|
| [开放插件市场 / dshopen.org](https://github.com/polang233/dsh-plugin-index/blob/main/.github/CONTRIBUTING.md) | GitHub Issue，维护者审核；可确认固定 Git 来源 | 仓库、版本、完整提交、子目录、许可证、安装与验证范围；无 npm 也可申请 |
| [awesome-dsh-plugin](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/blob/main/contributing.md) | PR 添加一个 `data/plugins` YAML；支持 monorepo 子包 | 指向 adapters/dsh 的链接、中英文功能介绍及分类；仓库需有 topic、真实 bundle 和维护 |
| [bruc3van/awesome-dsh-plugin](https://github.com/bruc3van/awesome-dsh-plugin/blob/main/CONTRIBUTING.md) | Topic 与简介进入发现/待审核流程，由维护者核实 | 已有 dsh-plugin topic、简介和真实可安装子包；自动发现不等于通过审核，自荐位还有单独要求 |

本项目已有公开源码、MIT、dsh.bundle.patch、固定版本和实装记录。社区是否接受、何时更新均由对方维护流程决定；当前不能使用其“已收录”或“已验证”徽章。

## 其他 Agent 如何发现

- **GitHub 检索**：About/topics 用于默认仓库搜索，README 需显式 `in:readme`。仓库已有平台、MCP、DSH、Scroll 等字段；它们让关键词可匹配，不承诺宽泛查询排名。
- **直接读取仓库**：从 [README](../README.md)到安装、能力状态和当前索引，均有可跟随的链接。Agent 不必先读交接或历史报告才能判断适用性与安装前提。
- **通用 MCP Registry**：另有 server.json、发布者验证及实际分发格式要求。当前 DSH tgz 不是可直接登记的 MCPB 包；也未发布通用 MCP npm/PyPI 包或托管远端服务。下一步应选定并验证标准分发形式后再提交，不能只补一个清单便宣称已收录。[官方要求](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/official-registry-requirements.md)。

不需要为了检索重复发布阅读核心、承诺没有实测的能力，或让 README 堆满术语。当前可执行的入口是上述 DSH 项目索引和[安装指南](dsh.md)。
