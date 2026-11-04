# Video Reader 项目索引

公开订阅地址：

```text
https://raw.githubusercontent.com/Kandecho/Video-Reader/main/discovery/dsh/index.json
```

这是作者维护的单项目 DSH format-1 索引，包含整包 Reader、通用队列/历史和 Scroll 的适配器。它与社区索引分别维护；2026-11-05 已核对[开放插件市场](https://dshopen.org/zh/plugins/dsh-video-reader/)收录同一 0.1.0，可订阅 `https://dshopen.org/index.json`。Awesome DSH 的目录 PR 也已合并，详见[收录状态](submissions.md)。

索引从已发布适配器提交 `f2656bf030ec94b9f6dfea22008c1d3168f4e4c6` 的 manifest 和中英文 locale 生成，版本为 0.1.0，安装来源固定到该 Git 提交的 `adapters/dsh`。DSH 索引格式支持 npm 或 Git，不能将 Release tgz 直接作为 source；原 tgz 仍是手动安装入口。

生成与检查：

```powershell
python tools/build_dsh_index.py --commit f2656bf030ec94b9f6dfea22008c1d3168f4e4c6
python tools/build_dsh_index.py --commit f2656bf030ec94b9f6dfea22008c1d3168f4e4c6 --check
```

更新版本时先发布并验证适配器，再从其完整提交生成；不要把安装来源改为浮动 main。补充检索词只覆盖已有字幕、画面和 Inbox 能力。发现路径及社区收录区别见[发现指南](../../docs/discovery.md)。
