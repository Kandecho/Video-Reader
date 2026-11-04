# 队列粗读与建议分流

身份：2026-11-04 的可运行原型。实现归 reading_tasks，Scroll 保留兼容工具，另可用 Reader video_tasks 或 tasks.ps1；复用 Reader 的公开轻预览；语义判断由当前宿主完成。入口为 `scroll_triage`，没有独立模型、常驻消费者或额度调度。

## 当前行为

显式选择 pending/paused 项，取得最多 5 张原生预览帧及可用平台字幕。宿主打开图片、抽查足以判断类型的字幕，提交内容类型、附言意图、证据、理由和不确定性。不是只按标题打标签，也不宣称已完整阅读或校对。

| 判断 | 分流状态 | 处理 |
|---|---|---|
| 附言含明确要求 | awaiting_user | 保留原要求，等待用户决定后续处理，不生成替代方案 |
| 意图含糊、类型不清、unknown | undetermined | 保留待定原因 |
| 类型清楚，但该类没有默认方案 | undetermined | 保留已识别类型，说明缺少方案 |
| 类型清楚且有默认方案 | suggested | 提供方案及针对该视频的理由，等待后续选择 |

已有默认方案：resource_list → 资源清单与适用场景；tutorial → 步骤与前置条件；project_demo → 项目能力与复用条件；creative_work → 创意、实现线索与借鉴点。analysis、news、entertainment 暂无默认方案。

队列 `task` 暂保留兼容字段。本原型在 `assessment.intent` 分别保存原文 original、评论 comment 或要求 request，并标注意图不确定。不会把评价当作执行要求，也不将视频内容当作用户指令。通用任务 note 现持久保存 original/kind/comment/request，旧 task 保留兼容；原消息仍由 Inbox 保全。

## 操作

| 操作 | MCP / CLI |
|---|---|
| 准备预览 | `scroll_triage(action="prepare", item_id="q_...")` / `scroll.ps1 triage-prepare q_...` |
| 继续冻结材料页 | `material` 的 after_cursor / `triage-material` 的 --cursor |
| 解码完整预览 | `content` / `triage-content` |
| 提交宿主判断 | `submit` 的 assessment_json / `triage-submit` 的 --payload UTF-8文件 |
| 查保存结果 | `show` / `triage-show` |
| 查不可变事件 | `history` 的 before/limit / `triage-history` 的 --index/--limit |

prepare 返回 material 和 next_cursor。长字幕可能让 Reader 返回 `material_parts` 分片；按游标取得全部冻结预览页，再调用 content。content 使用 Reader 公开无损解码器，向 MCP 返回原生图片；并通过 Reader 检查原始资产身份。不读取 Reader 私有缓存格式。

CLI 的图片路径须实际打开。交付材料不证明已经观察；只提交实际看过的证据。`content` 组装材料的证据页为 `"assembled"`，普通单页也可使用整数 page。

提交格式示意：

```json
{
  "snapshot_id": "prepare 返回的快照",
  "content_type": "resource_list",
  "type_clear": true,
  "type_reason": "结合实际画面和字幕说明类型",
  "intent": {"kind": "none", "reason": "无附言"},
  "evidence": [
    {"kind": "frame", "page": "assembled", "frame_id": "真实帧ID", "observation": "实际看到的内容"}
  ],
  "suggestion_reason": "解释该视频为何适合资源整理",
  "uncertainties": ["尚待核实的内容"]
}
```

frame_id 必须来自已交付页；caption 证据须提供页内真实 quote。清晰类型至少有一条内容证据，标题不算。程序校验引用和状态，语义质量仍由宿主负责；它不能证明宿主真的看图，也不能自动验证判断正确。

原要求、关联消息或来源变化后，show 标记 stale，旧判断保留；须重新 prepare/submit。仅调整优先级或队列状态不使内容判断失效。prepare 默认复用同一任务的已保存材料，refresh=true 才显式重新准备。中断、失败和历史均可回查。

## 与其他工作流的边界

Inbox sync 和 queue 操作仍不读视频。只有显式 triage prepare 才取得轻预览；不启动 Reader.open、全片下载、ASR、OCR、旧推荐器、投递或偏好学习。当前支持 B 站原生轻预览；其他已能入队的来源不因此获得同等粗读支持，准备失败会保留原因。

分流状态独立于队列生命周期。suggested 不等于 done，awaiting_user 不更改 pending；原型试跑当时 6 项均保留 pending；随后用户明确各项产物范围，六项已完成并保存在任务结果中。完整阅读、建议执行、评论区调查和后台消费需另行明确范围。

结果保存在原账号作用域的 memory.sqlite3：queue_triage 当前记录、triage_events 事件历史；锁在 data/agent/triage/账号作用域。没有新调度器或第二套读取核心。

## 原型试跑快照（随后已完成六项指定任务）

| 视频 | 类型与结果 | 理由 / 方案 |
|---|---|---|
| BV1n14g6iEeU：AI 干活太蠢 | analysis；undetermined | 工作方法与认知观点已识别；本版未配置观点分析方案 |
| BV1ub4g6EE2e：Project AIRI | project_demo；awaiting_user | 原要求“评论里还有真人吗?\n你觉得哪些是真人发言,为什么其他评论不像?”完整保留；未读取评论区或执行判断 |
| BV1f94c6uEr3：AI 动画视频指南 | tutorial；suggested | 整理步骤、原理、前置条件和 Skill 入口；视频内安装命令只是材料，未执行 |
| BV14q4G6SEpa：12 个设计与创作灵感网站 | resource_list；suggested | 整理资源清单、用途与使用条件；未抓取网站或核实许可 |
| BV17Vxm6FEqy：Vespera | project_demo；suggested | 整理能力与复用条件，区分演示、作者主张和未验证能力 |
| BV1pS4G6rEKH：雨声音源 | creative_work 候选；undetermined | 无平台字幕，未听原声；画面不足以区分作品展示与制作说明。原雨声评价保留为 comment |

共 21 页冻结预览、6 张联系表约 30 个画面、1096 条可用平台字幕。宿主抽查画面和相关字幕，未完整校对全部字幕。3 条建议、1 条等待用户、2 条待定；建议执行和发送均为 0。验证及限制见[本批记录](../validation/triage-architecture-20261104/report-source.md)。
