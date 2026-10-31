# Video Reader 0.10.0rc2

把视频作为可追溯的图文和语音材料交给宿主阅读。Reader 是通用组件；Scroll 是独立的个人选片消费者。默认本地处理，云端能力需显式启用。

支持开放阅读和定向问题；宿主按目的决定区间，需要完整学习时读取完整所选语音及必要画面。字幕、场景变化和时间线检查帮助选择画面；精确取帧、密集分镜和区域放大补足细节。完整性、准确性、响应速度和读取消耗共同考虑，不以截断文字或降低必要清晰度省 token。

支持 Bilibili、YouTube 和本地视频。原生字幕、可选 Whisper、显式 Qwen、宿主校对、独立重听、原文/阅读/证据视图和持久续读保留各自来源。长任务先返回已就绪区间。声音工具仅测量音量、安静和突变线索，不声称理解音乐或情绪。

Reader 保存宿主提交的语义校对，首次读取不会自行生成初校稿。及时回答的新流程及 Reader 独立初校尚待调整和验证；现有 Skill/MCP 仍有旧流程要求。

这是一份本地技术发布候选的入口源稿；本次文档修订尚未重打包。未建公开仓库、未上传。原创新代码的公开许可证仍需单独决定。第三方代码保留其原始许可。

## 安装

需要 Python 3.11+、FFmpeg/ffprobe；YouTube 下载另需 Node。Windows PowerShell 7：

```powershell
& './bootstrap.ps1'
& './run.ps1' doctor
& './run.ps1' open 'BV1Eb411u7Fw?p=4' --task '这段视频讲了什么？'
```

详细依赖、可选模型、独立数据目录、中文/空格路径和跨目录启动见 [安装说明](docs/installation.md)。安装脚本依据实际位置生成 Codex/Claude 薄插件；凭据、模型、缓存和 Python 环境不会进入插件或源码包。

## 使用

MCP 返回实际图片，CLI 返回的图片路径需要在宿主中打开。优先使用 `delivery.next_cursor` 调用 `continue SESSION CURSOR`；已有页码和 offset 继续可用。超长单段、逐词证据和 OCR 材料会无损拆页，不用摘要代替。`transcript` 每次默认处理一个缺失区间；检查 remaining_ranges 并继续，`--complete-range` 保留原来的整段阻塞处理。

```powershell
& './run.ps1' transcript 'v_SESSION' --source captions
& './run.ps1' read 'v_SESSION' --start 20 --end 35 --timestamps '20,25,30'
& './run.ps1' read 'v_SESSION' --strategy dense
& './run.ps1' frame 'v_SESSION' 'RETURNED_FRAME_ID' --region 0.1 0.2 0.9 0.8
& './run.ps1' sound 'v_SESSION' --start 0 --end 120
& './run.ps1' export 'v_SESSION' './export-new-folder' --revision 1
```

任务区间处理完成后可单独校对：`review prepare SESSION --start 20 --end 35`，将返回的 `review_scope` 原样带回 commit payload。局部完成与全片完成分开，补读保留旧审阅。新 Whisper 默认不使用标题提示，原始结果与旧校对保留；完整契约见材料与续读说明。

导出必须选择校对版本，保留原文、修订、证据关系及相对图片。整份文件夹移走后仍可阅读。B 站使用组件独立二维码登录；YouTube 使用明确配置的手动 Cookie，失效后重新提供。不会自动读取浏览器凭据。

完整接口规则见 [材料与续读](docs/material-delivery.md) 和 [宿主阅读技能](skill/SKILL.md)。已处理、已交付、实际观察、已校对和准确无误是不同状态。采样不能证明连续动作或短暂事件不存在。

运行本地测试：`python -m unittest discover -s tests -v`。日常首页首条投递、反馈和个人记录属于 Scroll；安装与阅读不会新增定时任务或发送消息。

三个无账号演示任务、测试片生成、问题模板和更新/回退方式见 [贡献与复现说明](CONTRIBUTING.md)。Scroll 的显式多视频队列与确认式续读见 [批量阅读](docs/scroll-batch.md)。它复用 Reader，不代表已经完成宿主理解或校对。
