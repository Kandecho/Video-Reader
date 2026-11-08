# 时间块目录、检索与历史回查

本地阶段 3/4 扩展，2026-11-06。Reader 新增 video_content；任务仍经 video_tasks。目录用于定位，原文、源图和校对留在原材料中，目录存在不表示已观察或已核查。

## 从哪里找到已有材料

先用 `video_tasks(action="queue-search", parameters_json='{"query":"superagent"}')` 查任务、结果摘要及已登记的 Markdown/文本产物正文。大小写、Unicode 兼容形式、空白和标点归一化，所以 Super-agent 与 superagent 可命中同一标题；不据此合并不同任务。

返回 matched_fields、已有结果、产物路径及有效性。文件不存在或 SHA 已变化时明确标记，正文不会被当作已保存版本搜索；大于 2 MB 的文件不做正文检索。只搜索任务登记的文件，不遍历其他项目或 Inbox 私有表。省略正文只影响导航，完整产物仍可按路径读取。

根据 item_id 用 queue-show 取得原要求、覆盖范围和产物。要追问原视频，从 canonical 或 existing_material 的 session 继续；没有完整媒体 session 不等于没有历史笔记或原生字幕。当前不提供跨全部视频正文的语义向量检索，未命中时可查相关任务、读产物引用，再进入选定视频的时间目录。

## 选定视频中的定位

`video_content(target, action, ...)` 的 target 可以是已打开的 v_ session 或 B 站 URL/BV。URL 优先复用同账号的完整媒体及已校对文字；缺少完整媒体时，复用原生字幕和近似分镜，不启动 ASR。其他来源先 video_open，再使用返回的 session。

| action | 用途 |
|---|---|
| index | 默认 120 秒时间块，返回导航文本预览、原段 ID/时间的接续入口、已有画面引用及缺口 |
| query | 词法候选：输入具体关键词，返回匹配词与块；宿主判断是否有关 |
| storyboard | 分页查看块内实际图像；原生分镜和源视频精确帧保留精度区别 |
| material | 指定唯一 block_id，取得完整正文段与相关图像，不将目录预览当原文 |
| validate | 校验指定 index_id 的冻结来源、账号、语音/校对版本和像素身份 |

首次 index 后，后续选择传 index_id 和返回的 block_ids；校对或原始材料变化会拒绝旧选择。块长 block_seconds 可为 15–600，默认 120；offset/limit 负责块分页，delivery.next_cursor 负责当前响应的无损分页，两个位置不能互换。

目录 text_preview 明确是导航，text_characters/text_preview_complete 标明范围；完整原段经 material 保留。跨块的长段会在相邻块保留同一 ID 和完整原文，不能把相邻出现误当新段。

query 采用 Unicode 归一化、英语词及中文二元词匹配，不是独立语义模型。文本未命中不排除无字幕画面或错字；回到 index/storyboard 选时间块，再用 read 的精确时间、frame 的裁切或 relisten 补证。完整建索引不成为所有回答的前提。

原生预览图会被后续预览复用，因此目录先保存 SHA 命名的稳定副本。源媒体帧校验 SHA；图像变化、丢失或账号不匹配明确拒绝。URL 找到已有校对 session 时不会退回未校对的预览正文。显式旧原生快照仍属于原生未校对轨，不能冒充新校对。

CLI 示例：

```powershell
& ./tasks.ps1 queue-search --query 'superagent'
& ./run.ps1 content BV1W64h6hEvf --action index
& ./run.ps1 content BV1W64h6hEvf --action query --query '事件 任务恢复'
& ./run.ps1 content BV1W64h6hEvf --action material --index-id ci_返回值 --block-ids ci_返回值:6
```

CLI/MCP 的 content 使用现有短等待 job，默认 1 秒；未完成用原 job ID 查询，不重复启动。Python API 保持同步；`_delivery=False` 保留块内完整正文，但仍按 offset/limit 分页；继续 next_offset 才能覆盖全部块。它不等于取消分页。

阶段 5 的双片对照支持“先读原文找疑点，再看同秒及邻域源帧”的按需用法。块中心帧可作导航，不能保证包含某句的术语、字幕或短变化。没有直接依据的词只留候选；画面与复听能暴露主转写整句遗漏，处理 complete 不表示语义无缺。具体对照和集成结论见[阶段 5 验证](../validation/stage5-reading-support-20261106/report-source.md)。
