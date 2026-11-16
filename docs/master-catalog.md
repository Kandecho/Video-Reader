# 本地任务目录

正式目录位于任务库下的 `catalog/index.html`，默认安装为 `data/tasks/catalog/index.html`。2026-11-14 已采用获批样稿并迁入v2契约：以单次任务为入口，先看状态、类型、具体要求和处置，再回查材料与成果。目录是任务库的HTML投影，不另建一份完成账本，也不移动原笔记和Casebook。

## 按任务查看

视频是可反复处理的材料。任务是有明确目的和完成条件的工作；读取、取帧、分包和校对属于处理记录，不因发生一次处理就新增任务。同一来源可以关联多项任务，各自保留原话、范围、状态和历次成果。

主筛选只使用**父任务的状态与类型**。“待完成”合并pending与paused，仍可单独查看暂停项；取消和归档分别显示。类型按任务库中的实际值生成，不预设封闭分类；未填写类型可以单独筛选。处置的状态和描述不参与这两个筛选，不把父任务done与某条pending处置拼成“已完成”。

关键词搜索覆盖任务描述、材料标题、原话、成果与处置等内容。批次仍按任务ID筛选，不因同源而混入别的任务。筛选条件保存在URL中，可刷新或复制当前视图。来源归组仍保留在数据快照中，正式页面以任务列表为主。

每项任务显示材料封面、具体要求、处置与成果入口。问答优先展开直接回答，笔记或评论原文作补充；历史版本、来源消息、完整覆盖和未核查范围在详情中。无成果待办也进入目录，手动done而无成果会明确提示。任务完成、材料已取得、完整观察与全片核验分别判断。

生成目录时，当前／历史成果与副本先写成静态相对链接，动态列表再复用DOM中的链接地址。这样Codex HTML预览可以先按工程边界处理链接，普通浏览器也能按目录位置解析；不在脚本中硬拼`file:`地址或宿主的内部映射地址。外部材料仍使用原网址，缺失文件保持不可点击。Codex预览会阻止工程外文件，保留原路径供在合适位置打开，不复制文件来规避边界。

## v2核心字段

核心字段由任务库维护，目录只作投影。

| 字段 | 含义 | 值域 |
|---|---|---|
| `state` | 任务推进到哪里 | 固定为pending、paused、done、cancelled、archived；不得为空 |
| `task_type` | 要完成哪类工作 | 可复用、可新增的短文本或null，最多200字符 |
| `task_description` | 具体对象、要求与完成标准 | 自由文本或null，最多4000字符 |
| `completion_method` | 必要时说明怎样结束 | 短文本或null，最多200字符；仅done时可非空 |

新增类型先查看 `queue-list.task_types` 或 `catalog-status.task_types`。候选包含同一任务库当前及历史用过的名称，相同目的优先精确复用；历史名称不代表当前仍有同名任务。含义不同再新增，不按视频主题或保存目录自动造类型，也不自动模糊归并。

旧 `task` 与 `title` 保留字符串契约和原有兼容入口，不改造成nullable字段；来源消息与用户原话另行保全。新建任务时，只有未传task_description才允许旧非空task初始化描述。之后明确清空的描述保持null，消费时可显式提供request，不能从标题或旧注记补造。有效评论仍作为评论背景，不自动成为要求。

旧 `result.catalog.task_goal`、`result.catalog.task_description` 和既有呈现注记保留历史，但不回退为当前canonical描述。新增结果可保存任务描述及语义身份快照；修改当前要求后，旧成果仍可回查，旧run不能据原要求完成新任务。

## 空值与更新

| 输入 | 维护规则 |
|---|---|
| 更新中省略字段 | 保留当前值 |
| 新增可选核心字段为null、空字符串或纯空白 | 归一为JSON null |
| purposes、tags或处置artifacts为 `[]` | 清空对应列表 |
| 必填state或处置description为null | 拒绝 |
| 从done改为其他状态 | 自动清空completion_method |

同样接受null的可选呈现文本包括retention、reading_depth、format、preview_path、keep、reason、目录显示title、notes、历史task_goal及primary_artifact_path；来源cover_path和处置reason／notes也可清空。purposes、tags和处置artifacts用列表维护。旧task／title原话及result答复不套用这套可选文本规则。

“未注明”“未填写”仅为界面占位，不写入字段。没有单独完成方式时保持null，不补“正常完成”；没有待办就不补“待确认”。已清空的值不从历史标签、标题或旧结果恢复，历史措辞仍可供下一次显式选择。

## 任务处置与保存理由

任务处置说明工作怎样落定，包括回答问题、保存笔记、另存已有成果或决定不另存。它可以附属于同一任务，不因整理后又保存副本就自动成为新任务。“学习一下”通常对应整理笔记，笔记去向另作处置；有新加工、整合或补证目的时再判断是否另立任务。

分别记录为什么处理材料、为什么把成果另存或不另存。实际答复已经说明的处置直接回查成果，不为显示“已回答”重复登记。需要独立保存留存决定、文件位置或待执行步骤时，使用兼容的 `followup-save/list` 入口；每条有状态、自由description、理由、说明、文件与修改历史。

副本实际保存并核对后才登记done。“无新增认识，不另存入知识库”可以是done且无新文件；“仅本地收藏”表示约定处理及成果保存已经完成，没有继续转存需求。已决定但未执行的处置保持pending／paused，可在搜索与详情中回查，不改变父任务筛选。未要求的分流或后续步骤不自动成为待办。

用户明确确认以终止结束时，可记录 `state="done", completion_method="终止"`。这表示约定处置已完成，未读取视频、未核查主张仍须如实保留；不能将所有cancelled一概改成done。

## 封面、成果与呈现元数据

封面由 `metadata.json` 中的 `source_metadata[canonical].cover_path` 维护，为本地图片路径或null。同源任务共享封面；路径缺失、文件不可用或显式清空时显示占位，不退回取帧或preview_path。封面只辅助对应材料，不是已读证据。

任务的 `primary_artifact_path` 是可选的主要成果展示覆盖值，只能指向该任务已登记成果中的文件。null表示不指定，由页面选择已有成果；它不登记新文件，也不能代替成果记录。直接答复可以是成果，无须有文件。

留存方式继续使用“简述索引、轻量记录、深度提取”，与用途、读取深度、目标格式及实际交付分别保存。format是目标格式；实际格式来自登记文件和答复，HTML目标只有Markdown时仍须显示差距。需要保存的成品默认HTML，重要信息可完整由文字承载时可用Markdown，详见[工作流契约](workflow-contract.md)。

## 维护入口

```powershell
& 'D:\IA\apps\video-reader\tasks.ps1' queue-list --state all
& 'D:\IA\apps\video-reader\tasks.ps1' queue-update 'q_任务ID' --payload 'task-update.json'
& 'D:\IA\apps\video-reader\tasks.ps1' catalog-build
& 'D:\IA\apps\video-reader\tasks.ps1' catalog-status
& 'D:\IA\apps\video-reader\tasks.ps1' catalog-update 'q_任务ID' --payload 'metadata.json'
& 'D:\IA\apps\video-reader\tasks.ps1' followup-list 'q_任务ID'
& 'D:\IA\apps\video-reader\tasks.ps1' followup-save 'q_任务ID' --payload 'disposition.json'
```

任务更新payload例如 `{"task_type":"整理笔记","task_description":null}`，更新类型并明确清空描述，其余字段保留。任务状态和完成方式通过queue-update维护。catalog-update收到task_type、task_description、completion_method时也分流到任务库；其他字段只更新呈现注记。

来源封面通过catalog-build的payload维护，例如 `{"source_metadata":{"https://www.bilibili.com/video/BV示例?p=1":{"cover_path":null}}}`；canonical须使用当前任务库实际来源值。task_metadata和views也由catalog-build维护。MCP使用同一 `video_tasks` 动作，payload可换为parameters_json中的result对象。

处置payload例如 `{"description":"存入 KIBRARY","state":"done","reason":"将已有笔记收入个人知识库","artifacts":["<knowledge-base>/inbox/笔记.md"],"source_result_id":52}`。先保存并核对再登记，只有计划时用pending。followup-list不传任务ID时返回同库处置及历史表达；更新时传原id，可用expected_revision避免覆盖并发修改。

首次构建后，新增任务、登记结果、任务或处置更新及Inbox入队会在数据库提交后刷新已启用目录。刷新失败保留已提交事实，返回catalog_refresh失败信息；重试catalog-build，不重复登记成果。页面“刷新目录”重新加载最近生成的文件。旧MCP进程须重载以使用新契约；新CLI和消费进程使用当前源码。查看目录不触发读片、收件、发送或后台恢复。

## 文件与迁移证据

catalog.json与index.html可由任务库重建。快照 `schema_version=2`，tasks包含全部任务；types是当前非空类型计数，task_types是同库历史建议。videos及旧stats.tasks仍只计有登记成果的任务，total_tasks、without_results、total_task_states表示全队列口径。metadata.json保存呈现注记、来源封面、视图定义和兼容历史，不作为第二份任务状态来源。

正式迁移后为42项任务、38个来源、91次成果登记、4条done处置，其中3条有知识库副本；当前40 done、2 paused。原请求、标题、消息关联、历次成果和处置逐项保全。小米下架项现为done＋终止，仍未读、未核查；日语整片和Summer任务继续paused。37个来源封面供41项任务共享，缺封面项显示占位。原5处成果文件变化标记保留，当前无缺失文件。

验收与迁移结果见[本批记录](../validation/catalog-formal-20261114/README.md)及migration-result.json（本地证据：`validation/catalog-formal-20261114/migration-result.json`）。迁移前任务库备份、目录快照及源文件清单保存在同目录before下，获批样稿保留为设计参考。历史批次只是当前目录的任务ID视图，旧JSON与稿件仍保留适用日期。
