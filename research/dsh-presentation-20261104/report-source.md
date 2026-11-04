# DSH 同类仓库如何对外介绍与分发

日期：2026-11-04。接续 [10 月 31 日同类项目考察](../dsh-video-ecosystem-20261031/report-source.md)，本批只研究仓库呈现、安装分发与发现入口，不重新评比阅读能力。元数据复查 10 个仓库，固定其中 5 个提交，读取其 README、package.json、目录和近期 Release；4 个包另查官方 npm 实际版本。固定来源与文件 SHA-256 见 [summary.json](summary.json)。没有安装这些项目或验证其功能承诺。

## 结论

值得借鉴的是连贯的入口：一句话说明用途，展示一次真实使用结果，给出可执行的安装方式，再让包、版本和反馈入口相互对应。关键词分布在 GitHub About/topics 和包元数据里；它们服务不同检索入口。仓库名字以 `dsh-` 开头不是自动收录机制，也没有证据说明某项设置带来了多少流量。

对 Video Reader，本批完成已同意的 About/topics 和检索基线，以及独立记录的 [DSH 实测](../../validation/dsh-integration-20261104/report-source.md)。适合随后讨论的投入是一个短演示、可安装的 DSH 薄 bundle，以及明确的目标索引；本批未发布 npm 包或申请目录收录。

## 五个可参考的做法

| 项目 | 首页怎样说明价值 | 安装与对外材料 | 可借鉴及需要警惕的地方 |
|---|---|---|---|
| [dsh-bili-watch](https://github.com/Sacredbluedragon/dsh-bili-watch/blob/2a81a45abb05a5de9dec2be94e20a3b8b7667357/README.md) | npm 版本、Node 和许可徽章；一句话用途；工作流图片 | npm 插件安装与独立 CLI 两条路径，包里有 repository/homepage/bugs/keywords | 用户可先判断用途和安装方式；升级解释较长，容易挤占前屏 |
| [dsh-bilibili-video-summary](https://github.com/Aurum807/dsh-bilibili-video-summary/blob/e3103a36857d4d8e7d43e6f308d6035c1bacdc07/README.md) | 先展示“用户发链接，助手给总结”的对话体验 | npm 安装命令、依赖自检、故障与限制；包中声明工具 bundle | 最接近当前 README 应保持的方向：先讲怎么用，不从内部架构讲起 |
| [CZX2244/dsh-bilibili](https://github.com/CZX2244/dsh-bilibili/blob/c53af9dee30cf04ee759ac6857d5803196fb2a95/README.md) | 英文入口并链接中文；工具名和用途清楚 | GitHub 直接安装、环境检查、截图目录、第三方声明；根包声明 bundle | 无 About 描述但有 `dsh-plugin` topic，说明元数据不齐也可能存在完整使用入口；不应照抄这种缺口 |
| [dsh-video2text](https://github.com/vlln/dsh-video2text/blob/66f1e34551aa2d931472fddeff674845f90b8360/README.md) | 一句结果导向描述；17 秒演示；界面图；中英文与 Release/Discussions 链接 | GUI 和 CLI 安装、安装后的确认动作；另给独立 Skill 路径 | 最值得借鉴的是短演示和明确的首次成功状态；无需为了模仿它给 Reader 新增前端 |
| [dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll/blob/f883d79fa536a2d1610dbb89796e6f48266103d7/README.md) | 演示视频、交流群、具体日常场景 | npm/GitHub/Release tgz 多条入口、问题反馈所需信息和二创说明 | 分发备选很具体，但首页的版本提示已落后，见下文 |

以上是源码与作者文档中实际可见的设置。图片、演示链接存在，不等于本批观看了演示或验证了所示体验。

### 元数据并没有完全统一

10 个复查仓库中，9 个带 `dsh-plugin` topic；`xiaoguangningyu/dsh-bilibili-kit` 没有 topics。多数 About 直接含平台、用途和 DSH 关系；CZX2244 的 About 描述为空。GitHub homepage 这次均为空或 null，但多个 package.json 另有 homepage 指向仓库，不能把两个字段混为一谈。全部仓库均标识 MIT；许可标识不是质量或兼容性的证明。逐项快照见 summary。

5 个深读样本的根 package.json 都声明 `dsh.bundle.patch`，并有 description/keywords/repository。GitHub topics 和 npm keywords 是两套字段，改一个不会自动更新另一个。`dsh-video2text` 还提供中英文 locale；其余样本缺少同名目录，不据此推断所有本地化或索引字段都不存在。

### 真实分发与文档会分叉

官方 npm 当次返回：`dsh-bili-watch` 0.4.6、`dsh-bilibili-video-summary` 0.3.4、`dsh-video2text` 0.2.2、`dsh-bili-scroll` 2.5.0，repository 均对应所查仓库。CZX2244 的 README 首推 GitHub 安装，本批不把同名 npm 包归给它。

`dsh-bili-scroll` 固定提交的包版本与最新 Release 都是 2.5.0，Release 有 tgz 资产；README 却仍提示 npm 为 0.1.7，并推荐 2.0.2 的下载直链。真实 npm 已是 2.5.0，因此这段提示在本次观察时已失效。这是可直接核实的文档漂移，不据此评价作者的发布动机。[固定 README](https://github.com/c1overzz/dsh-bili-scroll/blob/f883d79fa536a2d1610dbb89796e6f48266103d7/README.md)、[2.5.0 Release](https://github.com/c1overzz/dsh-bili-scroll/releases/tag/v2.5.0)、[npm 元数据](https://registry.npmjs.org/dsh-bili-scroll/latest)。

`dsh-bili-watch` 和 `dsh-video2text` 有近期 GitHub Release，但所查最新 Release 未附单独资产；Aurum807 和 CZX2244 的 Release 列表为空。发布可以依赖 npm 或 Git 安装，不能把没有 Release 直接理解为无法安装。[watch Releases](https://github.com/Sacredbluedragon/dsh-bili-watch/releases)、[video2text Releases](https://github.com/vlln/dsh-video2text/releases)。

## GitHub、npm 与 DSH 索引是三个入口

GitHub 默认仓库搜索主要查名称、About 描述和 topics；README 需显式 `in:readme`。npm 有独立包名、description、keywords 和 dist-tags。DSH 插件搜索则只查已配置的索引，不能因某仓库叫 `dsh-*`、带 topic 或已发 npm，就认定它已进入用户的插件市场。[GitHub 搜索规则](https://docs.github.com/en/search-github/searching-on-github/searching-for-repositories#search-by-repository-name-description-or-contents-of-the-readme-file)、[本项目固定官方源码考察](../dsh-adaptation-20261104/report-source.md)。

上次资料中的市场页面和下载数没有固定索引版本，本批不将其当作当前 DSH 收录事实或传播成效。此次只确认仓库设置和公开安装路径，未声明这 10 个仓库目前在哪些 DSH 索引中可搜索到。

## Video Reader 已实施的元数据

About 已更新并从 GitHub 读回：

> MCP video reader for Bilibili, YouTube and local files: timestamped transcripts, frame inspection and resumable reading, with local processing.

Topics 为 `mcp-server`、`video-reader`、`bilibili`、`youtube`、`ai-agents`、`local-first`。没有加 `dsh-plugin`：当前完成的是手动 stdio 接入实测，还没有发布 DSH bundle。GitHub homepage 保留原空值。

### 同一组真实查询的前后对照

GitHub 仓库搜索，第一页，每页最多 30 条；修改前后使用同一组查询和参数。下表是当次返回页内的位置，不是全站名次，也不保证下次仍相同。

| 查询 | 修改前 | 修改后 |
|---|---|---|
| `repo:Kandecho/Video-Reader bilibili mcp` | 未返回 | 返回 |
| `repo:Kandecho/Video-Reader bilibili mcp in:readme` | 返回 | 返回 |
| `"video reader" mcp is:public` | 7 个结果中未返回 | 8 个结果中第 5 |
| `bilibili mcp video is:public` | 前 30 未返回 | 前 30 未返回 |
| `youtube mcp video is:public` | 前 30 未返回 | 前 30 未返回 |
| `B站 视频 mcp is:public` | 前 30 未返回 | 前 30 未返回 |
| `bilibili timestamp frames is:public` | 0 个结果 | 0 个结果 |

这证明本次修改后，默认字段的限定查询可以命中。它不分别量化 description 与各 topic 的贡献；宽泛词仍没有足够曝光。另做了 3 条网页检索，合并返回结果未出现本仓库；没有逐查询排名测量，也不能据此判定搜索引擎整体未收录。

## 后续讨论的建议

1. 先补一个短而可回查的真实演示：贴链接、带时间点回答、追问画面、继续上次材料。展示 Reader 已有体验即可。
2. DSH 若作为首个传播目标，下一步应做复用现有核心的可安装薄 bundle、自己的 SemVer 版本和清楚的依赖检查，再选定并核实目标索引。手动接入实测已通过，仍不等于一条命令安装已完成。
3. 通用 Agent 发现另选一个具体目录入口，核对其提交要求，再决定适配包或清单。不要一次铺开多个目录，也不需要让 README 变成关键词堆。
4. 安装命令、版本和验收范围保持一个主维护入口；旧报告明确日期，避免把历史安装提示保留在首页当当前事实。

这些是讨论建议，不自动授权 npm 发布、第三方目录提交、社区发帖或持续推广。
