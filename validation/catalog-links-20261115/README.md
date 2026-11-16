# 2026-11-15 Codex预览中的目录成果链接修正

用户确认故障发生在Codex HTML预览：主卡“打开成果／笔记”和详情文件名都无法跳转。

## 原因与修正

本机ChatGPT／Codex 26.1106.6628的WorkspaceHtmlPreviewContent会在页面脚本运行前扫描静态HTML，将工程内相对`a[href]`映射到文件打开入口。它拒绝原始file URI、绝对地址和工程外路径。原目录由JavaScript创建全部成果链接，错过静态映射。第一轮只修正基准地址／拼file URI，不能解决这一宿主问题，已由本轮实现替代。

目录生成器现在将当前、历史成果及副本去重后写入隐藏的静态链接区。动态列表只按已登记路径查找静态节点，复用其DOM href；不猜测或生成宿主内部映射地址。普通浏览器使用原相对地址，Codex使用它已处理的地址。宿主阻止的链接仍不可点击，缺失文件不登记入口。

## 验证

- `python -m unittest tests.test_catalog_links tests.test_catalog tests.test_formal_catalog tests.test_catalog_api`：34项通过。
- `python validation/catalog-links-20261115/check_registered_links.py`：157个文件引用对应132个静态链接，全部仍指向原文件。
- 只读提取本机预览包中的纯URL／路径判定函数，未运行UI或导航：127个工程内相对链接通过，5个工程外链接被阻止；直接file URI也被阻止。
- 用户重开Codex预览后，实测《逃出布迪秀》的“打开笔记”和详情里的buddy-discussion.html，两处均能打开。这是当前样本的真实导航确认，不冒称逐点点击全部文件。
- 重建前后51任务、100次成果、完整性统计一致；没有修改或复制原成果文件，没有发送、同步Inbox或恢复暂停任务。

## 部署

现有MCP连接实测仍运行旧生成器：catalog-build留下未展开标记、生成0个静态链接。随后已用新CLI重新生成正式目录，当前页面包含完整132个静态链接。Reader／Scroll两套既有连接需重载，避免后续自动刷新用旧代码覆盖页面；未通过卸载、修改权限或强杀进程处理。

Computer Use拒绝file协议，未绕过该限制；真实点击由用户执行确认。工程外5个链接保持宿主边界，不复制文件规避。

`before/catalog_view.html`保留最初模板；含私信的目录基线仅保存在忽略提交的`data/catalog-links-20261115/before.json`。`reproduce-links.cjs`是第一轮地址解析实验，不是最终导航验收。
