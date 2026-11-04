# 显式粗读分流与整个 Video Reader 架构检查

日期：2026-11-04。针对用户指定的当前六条待办，完成可运行原型、真实材料试跑及全项目架构审查。当前工作区包含此前多批未提交修改；没有创建提交、发布插件或改动任务调度。

## 实现与真实结果

新增 scroll_agent/triage.py，Scroll CLI、旧 agent 桥和 MCP 均可调用 prepare/material/content/submit/show/history。Reader 继续只提供材料，当前宿主观察并提交语义判断；Scroll 保存类型、证据、原文与 comment/request 意图、建议理由及不可变事件。没有新增独立语义模型或后台消费者。

| 视频 | 内容判断 | 分流 |
|---|---|---|
| BV1n14g6iEeU | analysis，类型清晰但未配置默认方案 | undetermined |
| BV1ub4g6EE2e | project_demo，原附言明确要求辨别评论区真人 | awaiting_user |
| BV1f94c6uEr3 | tutorial，适合整理原理、步骤和前置条件 | suggested / procedure_guide |
| BV14q4G6SEpa | resource_list，适合整理网站清单、用途和使用条件 | suggested / resource_catalog |
| BV17Vxm6FEqy | project_demo，适合区分演示能力、主张和复用条件 | suggested / project_brief |
| BV1pS4G6rEKH | creative_work 候选；无字幕、未听原声，画面不足 | undetermined |

原附言精确保留；雨声评价归 comment，不当作生成/改音指令。六项仍 pending，判断均非 stale；建议执行与发送为 0，full_reading_completed=false。AIRI 未读取评论区，动画教程中的 Skill 安装说明没有执行。

## 实际材料和集成修复

本次使用原生轻预览：每项最多 5 帧，查看 6 张真实联系表，共约 30 个采样画面；可用平台字幕共 1096 段。取得 21 页冻结预览（7/1/10/1/1/1），宿主仅抽查判断类型所需字幕，不宣称完整校对。没有 full open、全片下载、新 ASR/OCR 或云端切换。

两条长字幕预览返回 material_parts。真实试跑发现初版分流只能处理普通字段，不能引用分片内原图。已接 Reader 公开 restore，补 content 操作、完整分页门槛、资产身份复核和原生 MCP 图片交付；不读取 Reader 私有缓存文件。新增测试覆盖该集成缺陷。

## 验证

使用正式组件 .venv/Scripts/python.exe，设置 PYTHONPATH=tests：

```text
python -m unittest test_agent test_agent_runtime test_scroll_daily test_scroll_batch
  test_scroll_runtime test_scroll_inbox test_scroll_triage test_plugins test_stdio_encoding
Ran 126 tests in 17.399s — OK
```

包含 12 项分流测试，覆盖请求优先、评论不变命令、未知/未配方案待定、拒绝仅标题/伪证据、字幕引用、快照和原文、账号隔离、陈旧判断、重启复用与事件、分页不冒充已观察、完整分片解码。首次收尾命令误用了系统 Python，缺少组件依赖；已纠正为正式环境，未安装新依赖。私有 unit-tests.log 保留最终命令输出。

新 stdio MCP 进程验证 Reader 19、Scroll 6 个工具；读取全部六项判断，与保存结果一致，content 返回 1 张原生联系表。CLI 与旧 agent 桥另作同项只读回查。已运行宿主连接仍需重连才能发现新工具，未发布/重装插件。

架构说明生成 8 个面板和 1 张主图，文字检查 0 警告。无界面浏览器只打开本地页面，拦截网络；1440 桌面与 390 手机宽度均无整页横向溢出和页面脚本错误。已实际查看主图与手机截图，不据此宣称跨浏览器或暗色主题全面验收。

## 整体架构审查

静态解析 video_reader/scroll_agent 共 52 个 Python 文件，索引包含 imports、定义起止行与 SHA-256。Reader → Scroll 唯一导入为 video_reader.cli 的旧兼容桥；Reader 业务核心和 MCP 不依赖个人推荐实现。另核对配置、启动器、插件构建和历史运行证据。当前工作区快照不是 Git HEAD，索引保留本地便于回查。

确认问题包括短链接解析的离线/预算旁路、默认 open 与深检查/会话长锁、收件借投递配置、Inbox/Queue 私有接口与表所有权、已有材料提示扫描 Reader 私有 manifest、task 混用、分散行为契约、Memory 兼基础存储以及纯队列服务触及 OCR 初始化。各项证据、影响、推断限制和处理状态在[整体架构检查](../../docs/architecture-20261104.md)。

短链行为用模拟 urlopen + 平台入口截断复现：Reader.preview(shortlink, offline=True) 在平台离线入口前调用 urlopen 一次，真实网络次数为 0。该确认缺陷未在本批修复，六个规范 BV 未触发。没有将审查扩为全局重构，也没有重跑无关的完整媒体性能基准。

结构化汇总见 summary.json；详细原生页、联系表路径、宿主判断、接口回查、CLI 记录和源码索引保留本地，遵循原 validation 忽略规则，不公开私人原始消息或账号状态。操作说明见[分流参考](../../docs/triage.md)。
