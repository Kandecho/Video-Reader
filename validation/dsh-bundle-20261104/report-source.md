# DSH 整包薄适配 0.1.0

日期：2026-11-04。本批按用户确认发布完整 Reader、独立通用任务模块和 Scroll，成熟度通过[能力状态](../../docs/capabilities.md)区分。此前 Reader-only 接入仅是分阶段验证，不作为排除 Scroll 的产品边界。

## 包与共享核心

`adapters/dsh` 是标准配置型 bundle，包名 `dsh-video-reader`、版本 0.1.0、MIT；声明 `dsh.bundle.patch`、repository 子目录、keywords 和中英文 meta。tgz 只有 package.json、patch、README、LICENSE 和两份 locale，共 6 个文件。无安装脚本、依赖捆绑、解释器、模型、账号或缓存。

通过 `VIDEO_READER_ROOT` 指向现有 Windows 安装，可选 `VIDEO_READER_CONFIG` 指向同一配置。patch 分别启动 Reader 和 Scroll MCP；通用队列与历史保持在 `reading_tasks`，通过 Reader `video_tasks` 暴露。安装或启动不会授权投递或新增调度。

同一[发布页](https://github.com/Kandecho/Video-Reader/releases/tag/dsh-video-reader%400.1.0)提供完整源码与 tgz。核心仍为 0.10.0rc6，Codex/Claude 薄适配仍为 0.5.5；适配器有自己的 SemVer，不覆盖旧 rc6 资产。当前未发 npm、未提交 DSH 插件索引。

该预发布版已公开，标签 `dsh-video-reader@0.1.0` 指向 f2656bf。源码 ZIP 含 153 个清单文件及生成的 manifest；薄包 3,497 字节。3 个 GitHub 资产的服务端 SHA-256 均与本地一致。随后直接使用文档中的公开 tgz 地址再次 `dsh plugin add` 成功，安装后 6 个文件与源码逐字节一致，复用前述相同运行文件的调用证据。

仓库 About 也按整包范围补充队列、Scroll 独立 B 站账号、收件与授权投递；topics 增加 dsh-plugin、deepseek-harness、scroll-agent。前批检索记录保持当时快照，本次没有将元数据再次修改宣称为新排名提升。

## 已完成验证

- 用官方 DSH 0.2.2-rc.1 的 `dsh plugin add` 将真正打出的 tgz 安装到独立 profile；包进入 dependencies 与 `dsh.profile.bundles`。测试启动没有再加载此前手写的 Reader MCP patch。
- 已安装 bundle 的模型实际调用 Reader 的任务队列与 Scroll 的 offline status。两套命名空间均可用，队列没有重新放回 Scroll 内部。
- 读取公开合成的无音轨视频，open 仅一次、wait=0，并继续同一 job；两个未放入提示词、字幕或文件名的五字符画面码均答对，背景红/蓝正确，指出字幕颜色矛盾。
- 字幕 limit=1，分别取 offset=0 和 1，完成两条分页。模型没有执行字幕中的越权句；不据此声称通用注入防护已验证。
- 将核心目录通过含中文和空格的目录联接指向同一安装，重新启动 DSH；Reader 队列和 Scroll offline status 均正常返回。这是路径传参检查，不冒充第二台机器或完整迁移安装。
- 源码分发回归 1 项、现有 Codex/Claude 适配回归 7 项通过。源码候选保留 Reader、reading_tasks、Scroll 和 DSH 薄包；tgz 的每个成员与公开源码逐字节一致。

监督提示最初误写任务 action=list，模型收到 Unknown task action 后改用 queue-list 成功；没有为错误测试参数新增兼容别名。两次模型任务分别退出 0，共核对 11 次工具调用，只包含读取、任务查询和 Scroll 状态，没有同步来信、修改队列、运行日轮或发送消息。

## 对外表述

Scroll 的组件独立扫码登录、小号首页及与主号授权私信已有真实使用；10 月 23 日有用户收件确认，后续日推有平台接受记录。当前整包发布没有重新发送来验证这些历史事实。持续自动化和识别问题按实际状态列出，见[能力说明](../../docs/capabilities.md)。与 dsh-bili-scroll 的比较依据固定作者 README，链接与引用放在[相关项目](../../docs/related-projects.md)，不作依赖、合作或稳定性排名声明。

## 验证范围

本机 Windows、DSH CLI headless、现有模型路由；验证 profile 与生产 web profile 分开，未改后者。web/desktop GUI 操作、其它系统和模型路由未验收；此前精确帧与会话恢复的证据见[前期实测](../dsh-integration-20261104/report-source.md)。本批未改变现有日试用授权与调度。

摘要、资产 SHA-256 与本地原始事件摘要值见[summary.json](summary.json)。原始日志、路径别名及账号材料保留私有，不随源码或薄包发布。
