# DSH 社区收录确认

日期：2026-11-05（北京时间）。本次核对既有申请的关闭原因、正式线上条目及另一条 PR 的状态，并更新当前文档。没有重新提交申请、评论、安装、运行模型或修改本机 DSH 订阅。

## 开放插件市场：已收录

[Issue #243](https://github.com/polang233/dsh-plugin-index/issues/243) 的状态为 closed，state_reason 为 completed。关闭时间为 2026-11-04T16:46:02Z，即北京时间 2026-11-05 00:46:02。维护者 polang233 在[确认评论](https://github.com/polang233/dsh-plugin-index/issues/243#issuecomment-6636422560)写明：“Video Reader 已按 0.1.0 固定提交收录”。关闭表示该申请完成收录。

直接读取正式[线上索引](https://dshopen.org/index.json)后，查到唯一的 dsh-video-reader 条目；[中文详情页](https://dshopen.org/zh/plugins/dsh-video-reader/)返回 HTTP 200，含该包名。索引记录与已发布适配器一致：

| 字段 | 核对结果 |
|---|---|
| 包名与作者 | dsh-video-reader，Kandecho |
| 版本 | 0.1.0 |
| 来源 | Git：https://github.com/Kandecho/Video-Reader |
| 固定提交 | f2656bf030ec94b9f6dfea22008c1d3168f4e4c6 |
| 子目录 | adapters/dsh |
| DSH 版本约束 | >=0.2.2-rc.1 <0.3.0-0 |
| 安装前提 | Windows、另装本地核心、VIDEO_READER_ROOT；私信与调度单独配置 |

核对时线上索引共 1,023 个条目，该数仅是本次快照。线上 JSON 摘要保存在同目录 summary.json；原始索引和 GitHub 回应仅保留本地私有证据。检查还读取了固定仓库快照 942cc9628ff37cfa699e883a5a9815cc23424daf 的 public/index.json，其中未匹配本项目；确认收录的依据是正式线上索引及维护者确认，不将仓库静态快照当作已同步的服务端目录。

用户可在 DSH 添加 `https://dshopen.org/index.json` 后搜索 `dsh-video-reader`。本次没有声称重新完成社区源的宿主模型搜索或安装验收，既有作者索引实测仍按原范围保留。功能支持范围见[能力状态](../../docs/capabilities.md)。

## Awesome DSH：已合并收录

[PR #12055](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/pull/12055)现为 closed、merged=true。合并时间为 2026-11-04T17:26:10Z，即北京时间 2026-11-05 01:26:10；合并提交为 18fdd9b4d69a506a3b4519742113574785a2fc78，原分支为 ad751a4c4cc78a2d482e21f93c2cb6a774859210。[PR check 41851438969](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/actions/runs/41851438969)已完成，conclusion=success。

已在[合并提交的目录源](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/blob/18fdd9b4d69a506a3b4519742113574785a2fc78/data/plugins/Kandecho__Video-Reader--adapters-dsh.yml)核对条目，blob 为 267bfd2705068150332dde5c9ecdc18d870a1a37。名称 Kandecho/Video-Reader#dsh-video-reader、adapters/dsh 仓库链接和中英文描述与原提交一致。前次回查尚为 open 的记录已由这次合并核对更新；两条社区申请均已完成收录。

## 文档更新范围

README、DSH 安装与发现指南、作者索引说明、社区申请资料、文档首页、知识路由、交接及路线基线分别反映两条状态。11 月 4 日的发布回执仍保留当时待审核快照，并链接本次确认；已归档历史不改写成后来发生的结果。阶段顺序和运行行为未改变。
