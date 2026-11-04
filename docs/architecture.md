# Video Reader 当前架构

身份：2026-11-04 任务拆分与发布后的当前架构。核心 0.10.0rc6，Codex/Claude 适配器 0.5.5，DSH/MCPB 适配器各 0.1.0，整包已发布。Reader、通用任务与 Scroll 三个模块域，两套 MCP；不需要额外服务。

## 分层与调用

| 层 | 职责 | 主要实现 |
|---|---|---|
| 当前宿主 | 理解、任务判断、语义校对与回答 | 阅读 Skill、调用者 |
| Reader | 来源、账号、获取、预览、图像/OCR、字幕/ASR、复听、评论/弹幕、材料分页、修订和导出 | video_reader |
| 通用任务 | 队列、附言意图、来源引用、分流、批读、结果和操作历史 | reading_tasks |
| Scroll | 私信 Inbox、原消息/同步历史、个人推荐、偏好、日轮、投递及任务汇报 | scroll_agent |
| 本地基础 | SQLite 连接、模型、账号材料缓存、进程/锁与持久状态 | Store、Reader jobs、各业务执行者 |

Reader MCP 20 个工具，其中 video_tasks 是通用任务适配入口；Scroll MCP 7 个工具，增加 scroll_report。旧 Scroll queue/triage/batch 名称兼容，实际执行同一 reading_tasks 实现。tasks.ps1 可直接管理任务，不必经过 Scroll 或登录。

Reader 核心不导入 Scroll。材料语义与偏好策略不混入获取核心。任务只调用 Reader 的公开材料目录、语音身份索引和读取/续读接口，不扫描私有 manifest 或调用 _speech。

## 已修复的中高问题

| 原问题 | 当前处理 |
|---|---|
| 短链接解析先于离线/预算检查 | resolve 仅解析身份；短链由 Platform 受控展开，使用同账号缓存、预算和暂停；不自动跟随任意跳转 |
| 默认深核验拖慢回答 | 默认 open/read 不算新时序 OCR；普通文字阅读复用已缓存核验。temporal=true、verify=true 或 evidence 视图按需深入，原文与未核查路径保留 |
| 精确补帧被长会话锁阻塞 | 不可变媒体的细节帧使用独立资产锁与 frame-details 记录；普通保存不会丢掉并行生成的细节，校对仍可引用 |
| 通用队列绑到 B 站账号和个人 Memory | reading_tasks.Store 提供连接和稳定库身份；本地查询无登录，Memory 与 FTS 不再是队列前置条件 |
| Inbox 与 Queue 表、私有方法交叉 | Inbox 拥有原消息与同步表；通过公开事务内入队/来源接口连接任务；任务保存中立来源快照和独立事件 |
| 收件白名单借投递配置 | inbox.sender_uid 独立；旧值只在迁移时钉住一次，后续发信收件人变化不影响同步范围 |
| Scroll 扫描 Reader 私有缓存 | Reader.materials / catalog 公开查找；speech_index 提供批读所需身份和修订信息。状态汇报跳过无用的材料目录扫描 |
| 附言与要求共用 task | 原 task 兼容，任务 note 保存 original/comment/request/uncertain；分流提交与意图保存同事务，历史保全 |
| CLI/MCP/Skill 行为漂移 | 共用任务 action 与参数契约；阅读主策略由 reading_policy 提供，MCP、源码 Skill 与生成插件同步并有回归检查 |

初步分流与任务完成保留两条轴：旧建议或等待用户仍是当时判断；后续明确任务完成后另存结果，不把旧快照改成“从未待定”。Scroll 汇报同时展示两者。

## 材料与结果路径

通用任务调用 Reader，得到 p_ 预览或 v_ 完整媒体会话。CLI/MCP 长处理使用 j_ job；分页与资产身份冻结，交付不等于观察。宿主按用户目标读取、核查和生成产物；任务记录结果路径、哈希、完成依据及覆盖范围。校对修订继续属于 Reader。

私信原消息和游标归 Inbox；queue_origins 保存任务所需来源引用与原附言，queue_events 记录任务事件；queue_triage / triage_events 保存初步判断；task_annotations 保存意图；task_results 追加产物版本。个人 memories、runs 与 deliveries 仍归 Scroll。

当前 SQLite 可以共用物理文件，表所有者及接口独立。这样保留收件与入队的原子性，无需提前引入跨库补偿或消息服务。材料文件仍在 data/cache、data/preview；任务运行元信息在 data/tasks；本批六项产物位于 data/reading-results/20261104。

## 保留与调查结果

- Windows MCP 的 OCR 预导入继续保留。既有证据涉及原生库首次在线程内导入的启动死锁；尚无安全移除依据。独立任务 CLI 不经过 OCR 预导入，未再拆一套服务器。
- SQLite 连接已随 Store 抽出；没有为低项增加数据库服务。公开材料目录仍在 Reader 内扫描文件，若以后出现实际规模瓶颈再引入索引。
- 历史 Windows 原子替换失败缺少一致根因，本批不扩成所有存储重写；保留既有 job 状态短锁。Qwen 强制中文退化也仍是既有识别问题，不据架构调整宣称修复。
- AIRI 原始评论末页显示总数与顶层分页不一致。保存原始计数和 partial，不凭猜测把结果改成全量；这属于来源覆盖调查。
- 默认本地、Gemini 关闭，无失败自动转云。平台预算、本机资源与宿主模型额度仍分别看待；本批没有额度调度或常驻队列消费者。

## 操作与验证

入口见[通用任务](tasks.md)、[Reader 参考](reader-reference.md)、[Inbox](inbox-queue.md)和[Scroll](scroll-reference.md)。旧架构检查的九项原始结论见[修复前快照](architecture-20261104.md)，本页维护当前结果。

六项指定任务已交付并登记 done，原附言、关联消息和初步分流均保留。完整测试、真实 CLI/新 MCP 回查及不发送的报告验证，见[修复记录](../validation/architecture-fixes-20261104/report-source.md)。旧连接需重启加载新工具；当前发布范围见[能力状态](capabilities.md)。后续按[六阶段路线](../planning/roadmap-20261021-source.md)推进，交互改进优先复用本页架构和接口。
