# DSH 索引发现路径实测

日期：2026-11-04，DSH 0.2.2-rc.1。已完成作者索引公开、本机 DSH 检索、按检索结果安装、安装后状态和 Reader/Scroll 调用；同时调查社区收录与跨宿主发现入口。未修改 0.1.0 发布资产或阅读核心。

## 真实链路

[作者索引](https://raw.githubusercontent.com/Kandecho/Video-Reader/main/discovery/dsh/index.json)为 DSH format 1，由 tools/build_dsh_index.py 从已发布的 f2656bf 完整提交读取 manifest 与中英文 locale。不是从浮动工作区拼出版本；source 指向该提交的 adapters/dsh。补充检索词覆盖实际字幕、画面和 Inbox 能力。通过本机 DSH 官方 parseMarketIndex 校验，英文说明 273 字符，在工具的 300 字符限制内。

全新 vr-discovery profile 初始只含官方 base/headless，通过 DSH 原生 plugin-market 服务和只读工具接入作者索引及一个社区索引；沿用本机既有模型与原生凭据。真实模型先 list_indexes，测试以下查询，再 list_versions：

| 作者索引查询 | 返回 | 当时状态 |
|---|---|---|
| video reader | dsh-video-reader，1 项 | not-installed，0.1.0，compatible=true |
| 字幕 画面 | 同上 | 同上 |
| 账号 私信 | 同上 | 同上 |

工具给出的精确安装目标为：

```text
git+https://github.com/Kandecho/Video-Reader.git#f2656bf030ec94b9f6dfea22008c1d3168f4e4c6&path:/adapters/dsh
```

实际使用该值安装成功；新 DSH 模型进程再次查询为 installed，然后通过 Reader video_tasks 的 queue-list 和 Scroll offline status 成功取回状态。两个任务均退出 0，共核对 13 次工具调用；未同步 Inbox、修改任务、运行日轮或发送消息。安装后的 6 个包文件与固定发布提交的文本一致。

第一次监督调用显式经过 Windows dsh.cmd，参数中的 &path 被 batch 包装器拆开，导致 pnpm 尝试仓库根目录。直接用 Node 调用同一 DSH CLI 后保留完整参数并成功。属于调用边界问题，没有为此修改 DSH 或插件核心。

## 本机常用 web profile

已备份 package.json、cordis.patch.yml 和原 launch.ps1；启用 DSH 自带的实验性发现 bundle，加入项目索引及只读 plugin_market 工具，并安装同一固定 Git bundle。原启动脚本在未提供 VIDEO_READER_ROOT 时指向已有核心，不覆盖用户显式变量。

配置组合检查通过；短暂启动 web 后，HTTP 返回预期的 401 访问围栏，日志记录两个 ListToolsRequest，没有核心目录缺失或重复工具错误。测试服务已停止。此为配置和启动验证，不是逐项 GUI 点击验收；下次正常启动可在发现页使用该索引。

## 社区收录观察

本次直接获取的两个公开索引均为 HTTP 200、format 1，无重定向：开放插件市场含 1,011 项，realguan 源含 8,266 项；按精确包名与仓库核对均未包含本项目。开放市场的模糊查询会返回其他近似包，不能因为结果非空就说本项目已收录。数量只是本次快照，不是质量或曝光指标。

- 开放插件市场接受公开 Issue，由维护者审核；没有 npm 时可以确认固定 Git 来源，需给版本、完整提交和子目录。[固定贡献指南](https://github.com/polang233/dsh-plugin-index/blob/bae4d618038586ffb5d1976a1c53803ec2009177/.github/CONTRIBUTING.md)。
- awesome-dsh-plugin 接受单一 data/plugins YAML 的 PR，支持 monorepo 子包；要求实际 bundle、公开维护和准确介绍。[固定规则](https://github.com/awesome-dsh-plugin/awesome-dsh-plugin/blob/c4261924d2d8845901faaae5d0e6301a75afafa5/contributing.md)。
- bruc3van 的目录按公开仓库、Topic、简介发现候选并审核；自荐位的星标门槛不同于普通发现条件。当前没有证据证明本项目已进入待审核列表。[固定规则](https://github.com/bruc3van/awesome-dsh-plugin/blob/3571845393dd81119cfe3e348a8161fed4edc38a/CONTRIBUTING.md)。

[具体提交资料](../../discovery/dsh/submissions.md)已整理，未发送公开 Issue 或 PR。自建索引可被订阅，不等于已获社区审核或自动出现在所有人的 DSH。

## 其他 Agent 的检索

GitHub 仓库搜索第一页、每页 30 项，本次返回：

| 查询 | 返回数 | 本仓库在返回页的位置 |
|---|---|---|
| topic:dsh-plugin bilibili mcp | 20 | 11 |
| topic:dsh-plugin "video reader" | 2 | 1 |
| bilibili queues mcp is:public | 2 | 1 |

这是当前组合词查询的可见性，不是通用网页搜索的排名提升对照。README 已链接发现指南、安装与能力范围，便于 Agent 从命中仓库继续判断。

通用 MCP Registry 支持 GitHub/GitLab Release 上的 MCPB，另有 server.json、发布者验证和文件摘要要求；当前 DSH tgz 不是 MCPB。可以在复用现有核心的前提下优先验证 MCPB，而非先假设必须发 npm。本批未制作或登记通用 MCP 分发包。[固定官方文档](https://github.com/modelcontextprotocol/registry/blob/7809e442458c0118f0512d58af943ba3fb050787/docs/modelcontextprotocol-io/package-types.mdx)。

## 检查与证据

索引工具 3 项测试验证固定发布来源、拒绝浮动 ref 和私有/非 bundle；源码分发回归 1 项通过，确保候选包含新工具与索引。公开摘要保存源码指纹、原始事件摘要值及观察范围；账号、模型凭据、web 一次性 token 和本机配置留在私有区。见 [summary.json](summary.json)。
