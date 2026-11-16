# 正式任务目录与字段契约迁移

适用日期：2026-11-14。本次按用户确认的任务目录样稿更新正式目录，并同步任务库、CLI/MCP、消费流程、源Skill及项目内生成适配器。

## 采用的模型

视频是可反复使用的材料；下载、读取、校对等属于处理记录。任务有明确目的与完成条件，主要维护固定枚举 `state`、可添加并优先复用的 `task_type`、具体 `task_description`。`completion_method`另存完成方式，仅在done时可非空。

目录按父任务状态及类型筛选。保存目的、答复、笔记去向、另存或明确不另存等处置单独呈现，可搜索，不冒充新任务或父任务类型。已有直接答复即可表达问答任务的处置，无须重复登记“回答了问题”。

## 空值与修改

| 字段 | 空值 | 更新时省略 | 显式清空 |
|---|---|---|---|
| state | 不允许；新任务默认pending | 保持 | null、空串均拒绝 |
| task_type、task_description | SQL/JSON null | 保持 | null或空白文本转为null |
| completion_method | null | done中保持；离开done自动清空 | null或空白文本转为null |
| 目录可选文本注记、来源cover_path | null | 保持 | null或空白文本转为null |
| purposes、tags | [] | 保持 | []；旧null输入兼容为[] |
| 处置reason、notes | null | 保持 | null或空白文本转为null |
| 处置description、state | 不允许 | 更新时保持；新处置state默认pending | null、空白拒绝 |
| 处置artifacts | [] | 保持 | [] |

空类型在页面显示“未注明”，空描述显示“未填写任务描述”；这些是显示占位，不入库、不参与类型历史。明确清空后重建目录或升级不得从旧任务、标题、result.catalog注记恢复。类型候选由同任务库当前值及事件历史提供，不自动合并近义词。

旧 `task`、`title` 兼容字段仍为字符串，原话、来源及旧成果保全。首次升级只为旧任务初始化描述，已确认的评论附言不初始化为工作要求。新建时未单独给描述可由非空旧task初始化；显式null保持空。消费空描述必须显式给出实际request。新结果保存当时描述，描述改变后目录标明已有成果对应此前要求；旧结果无快照字段时保留未知。

## 迁移与保全

- `backup-before.py`使用SQLite备份API保存迁移前数据库，并保留旧页面、元数据及相关源码；清单见 before/manifest.json（本地证据：`validation/catalog-formal-20261114/before/manifest.json`）。数据库包含私有来源快照，仅用于本地维护。
- `adopt-catalog.py`是本次一次性迁移记录，不作为后续日常刷新入口。它使用批准样稿的类型和具体描述，写入正式列并追加迁移事件，运行前后比对原话、来源、意图、结果和处置。后续仅用queue-update维护字段、catalog-build重建目录，避免再次应用旧映射。
- 42任务、38来源、91次原成果、4条处置均保全。当前40项done、2项paused。原关闭项按用户确认改为done＋终止，类型null；其未读取、未核查证据保留，没有补造阅读完成。
- 当前8个非空类型，1项空类型，41项完成方式为空。3条“存入 KIBRARY”和1条“不另存入知识库”沿用既有已核对处置，本轮没有重复制笔记。
- 37张本地封面按来源共享，覆盖41个任务；1份来源无封面显示占位。正式目录不访问网络，不把视频帧当封面。
- 0个原成果文件缺失；5个原有文件变化标记保留。3个知识库副本仍存在且哈希匹配。

迁移结果见 migration-result.json（本地证据：`validation/catalog-formal-20261114/migration-result.json`）。正式入口为 index.html（本地证据：`data/tasks/catalog/index.html`），样稿保留作历史。

## 验证

任务字段、目录、API、处置、队列、消费、Inbox、分流、后台及适配器等相关测试共201项通过。部分旧测试按顶层名称引用tests内fixture，运行时将tests加入sys.path；首次未配置导致的3项模块导入错误已用正确入口补跑，61项通过。

离线浏览器检查见 browser-check.cjs（本地证据：`validation/catalog-formal-20261114/browser-check.cjs`）及 browser-result.json（本地证据：`validation/catalog-formal-20261114/browser-result.json`）：正式字段、父状态/类型筛选、新类型、显式空值、同源多任务、共享封面、Grokbot结果91、版本历史、3份知识库副本、明确不另存、终止未读、批次、旧链接兼容、刷新及跳转恢复、文件缺失提示、桌面明暗与390/320窄屏。描述改变时的旧成果提示、无旧快照时的未知兼容均已覆盖，真实页面无脚本错误。

刷新检查曾在页面loading时读取空输入框；diagnose-reload.cjs（本地证据：`validation/catalog-formal-20261114/diagnose-reload.cjs`）确认URL和加载后值正确，检查已等待load再读取。

工作流契约HTML从最终Markdown重建，STE零提示；离线桌面1440及手机390排版、关键字段与页面脚本检查通过，见 workflow-result.json（本地证据：`validation/catalog-formal-20261114/workflow-result.json`）。

源Skill与项目内Codex/Claude适配器已升至0.5.9。按项目维护规程通过已配置的本地市场更新既有安装，没有手改宿主缓存。两端均查询确认0.5.9且启用，实际读取的5个薄文件逐项与生成内容哈希一致，见 adapter-result.json（本地证据：`validation/catalog-formal-20261114/adapter-result.json`）；Claude继续从本地生成目录读取。生成及安装后的适配器与消费相关22项测试在项目 `.venv` 中通过。

CLI和新启动进程使用新契约；已连接的旧MCP与现有会话需要重载。本次未触发读取视频、收件、发送、后台启用、Git提交或发布。
