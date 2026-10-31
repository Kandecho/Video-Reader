# Qwen 独立参考、时间对齐与切分实验

这是正式 Video Reader 0.6.1 之外的本地候选引擎。不会改变默认 Whisper，不会写入既有会话或替换宿主校对稿，不启用 Gemini。复用 `../asr-engine-20261021/.venv`，应用包及模型仍全部保存在本组件内。

## 直接运行候选引擎

```powershell
$python = 'D:\IA\apps\video-reader\research\asr-engine-20261021\.venv\Scripts\python.exe'
& $python -I 'D:\IA\apps\video-reader\research\qwen-foundations-20261021\decode.py' 'D:\path\video.mp4' --start 16 --end 29
```

入口只接受本地媒体，不接受网络 URL。用正式 `open` 获取的视频可传入其 manifest 的 `media_path`。每次调用在本目录 `runs/<随机ID>` 保存实际输入音频、分块原文、全部对齐单元及最终 JSON。返回原视频的绝对秒数；start/end 为截取范围，不能重复加时间偏移。

默认名义区间为 60 秒，每侧补 2 秒上下文；首尾按源音频裁切。120 秒对齐在 8GB 显卡上接近显存上限并明显变慢，该轮已中断并保存证据，不作为成功的全片对齐。中文通常逐字、拉丁文本通常逐词，不是假设中文分词。保留跨边界单元的真实估计起止，不强行压到区间边缘。保留原文标点及真实重复，不做词串去重或全局同音替换。

先用单元中点建立左闭右开的初始归属。若同一时间附近存在唯一共享相邻单元对，且发现该对内的单元被双方都保留或都丢弃，则在共享对之间拼接。两窗口对应单元中点差不超过 0.25 秒，候选切口距名义边界不超过 0.5 秒，且原来的两个切口都位于这对单元范围内。只改有冲突的局部归属，不改变已一致的边界。歧义、快速重复或无共同锚点时保留中点结果和告警；零时长单元不能作为锚点。

每个窗口保存 raw_text/raw_words，最终 text/words 只包含本窗口所属内容。接缝前后 0.8 秒的两个窗口候选不同时保留 disagreement；即使文字相同，所属单元的时间重叠仍标为 requires_review。不能把重叠策略当成消除了所有漏字和重复。非有限、倒序、超出输入音频的对齐会使调用失败；零时长单元仍保留告警。失败没有云端或 Whisper 自动回退。局部结果保存在 partial.json，不等于完成结果。

时间戳来自官方 ForcedAligner 的模型估计。配置的时间分类步长为 80ms；这不是已测误差上限。尚无独立人工逐字时间真值，输出小数三位不等于毫秒级精度。对齐识别文本不等于纠正文本，更不等于听懂音效。宿主改写后的文字尚未自动重新对齐；也尚未接入正式八个 MCP 工具。

raw_words[].owned 保留初始中点归属；最终 words[].midpoint_owned 保留该原值，words[].owned 表示最终选中。selected_raw_indices 指明原始单元的半开索引范围。seam_cuts 保留实际使用的共享对或中点回退依据；owner 仍表示名义区间，不是对单元时间的强行裁切。

## 重现评测

已冻结的 reference.json 不能在看到结果后覆盖。24 个不同句子的音频、原始参考和发布者规范参考分别保留；仅向识别器传音频及语言，不传参考、标题或术语提示。

```powershell
& $python -I 'D:\IA\apps\video-reader\research\qwen-foundations-20261021\benchmark.py' qwen
& $python -I 'D:\IA\apps\video-reader\research\qwen-foundations-20261021\benchmark.py' whisper
& $python -I 'D:\IA\apps\video-reader\research\qwen-foundations-20261021\benchmark.py' qwen --boundary-stress-only
& $python 'D:\IA\apps\video-reader\research\qwen-foundations-20261021\restitch.py'
& $python 'D:\IA\apps\video-reader\research\qwen-foundations-20261021\summarize.py'
& $python -m unittest discover -s 'D:\IA\apps\video-reader\research\qwen-foundations-20261021' -p 'test_qwen_pipeline.py' -v
```

已有完整结果按冻结参考哈希检查后跳过，不重复采样挑选输出。分块 partial 文件不作为完整结果。Whisper 使用现有 CPU int8/4 线程、beam 5、无 VAD、无前段条件和提示、temperature 0；Qwen 使用 GPU float16、SDPA、batch 1、max_new_tokens 4096、无提示。时间不含加载、下载及宿主校对，不是等硬件模型速度对照。

results/ 保留全部原始模型输出和最初中点拼接。发现实际边界重复后，在不重跑模型、不改参考的前提下，用 restitch.py 生成 results-stitched/；每份派生结果保留原文件 SHA-256。summary.json 采用最终拼接，并同时保留中点压力组指标；midpoint-summary.json 为旧汇总。共享锚点的工程修复已用该压力样本检验，因此压力组不是修复后的独立确认集。24 条无接缝参考的 CER 不受这次拼接修复影响。

CER 以发布者规范参考为准，NFKC、casefold，去空白及 Unicode 标点；不改数字表达、不转换同音词。累计 S+D+I 除以累计参考字符，不能把逐条 CER 的简单平均当总 CER。参考是独立于本次识别输出的已发布朗读脚本，不是本项目重新人工复听的逐字稿。不能保证模型训练没见过 FLEURS，也不能代替专业视频参考。

boundary-reference.json 在解码前固定：前 8 条参考音频，再重复第一条，插入已知静音。按 20 秒任意位置切分，比较旧式无重叠原文拼接与 2 秒重叠/强制对齐。看过首组结果后，新增 7 秒短切分压力组，保留全部结果，不选择性汇报较好的一组。默认 60 秒来自显存约束，不是从压力组挑出的最佳字错率配置。参考总字错率和人工插入静音的占用可独立检查；具体汉字起止时间仍没有人工真值。

## 来源与许可

- Google 发布的 [FLEURS](https://huggingface.co/datasets/google/fleurs)，普通话 cmn_hans_cn test；CC-BY-4.0，作者为 FLEURS 团队。保留发布者 README、原始 TSV 和音频归档。官方版本、文件 SHA-256 及权重 LFS 比对分别见 dataset-provenance.json、模型目录 model-provenance.json。
- [Qwen3-ForcedAligner-0.6B](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)，Apache-2.0，Qwen 团队。实现调用已安装官方 qwen-asr 0.0.6 API，没有复制其模型代码。与 ASR 共用的官方许可原文见 ../asr-engine-20261021/licenses/Qwen3-ASR-Apache-2.0.txt。
- 新实验没有新增 Python 包；原环境的安装版本与各自许可见上一轮清单及本轮 environment.json。
