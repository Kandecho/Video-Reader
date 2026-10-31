---
title: 视频错字修复：转写与笔记项目调查
subtitle: 2026-10-21 · 8 个项目、36 份源码/文档 · 结合 Video Reader 0.4 的真实错例
template: doc
theme: paper
lang: zh
---

## A 调查结论

值得引入的是独立的逐字稿校对阶段。它结合完整语境、术语证据、画面文字和局部复听，产出可直接阅读的校对文本。原始转写保留为证据。

0.4 已能保留原文、发现部分画面冲突，但还没有完成这一步。下一轮应交付实际可用的校对稿，逐项记录改了哪些字及依据。

笔记项目可以提供实现参考。需要区分笔记的可读性和逐字稿的准确性：摘要会省略、合并、改写表达，不能用来衡量逐字转写质量。

## B 参考项目如何筛选

这些是本轮 GitHub API 的现场数据。Star 和维护活动用于筛选参考，不代表活跃用户数或识别准确率。

| 项目 | Star | 最近推送 | 本轮看到了什么 |
|---|---:|---|---|
| [BiliNote](https://github.com/JefferyHcool/BiliNote) | 7,579 | 2026-09-01 | 本机及上游 Whisper → 笔记链路 |
| [VideoLingo](https://github.com/Huanshere/VideoLingo) | 18,860 | 2026-09-30 | 本地 ASR、术语表、断句、词级对齐 |
| [pyVideoTrans](https://github.com/jianchang512/pyvideotrans) | 19,477 | 2026-10-15 | 识别后独立调用 LLM 纠错，支持热词 |
| [OpenCreator，原 KrillinAI](https://github.com/krillinai/OpenCreator) | 13,764 | 2026-10-20 | 字幕词汇映射替换、字幕结构处理 |
| [WhisperX](https://github.com/m-bain/whisperX) | 24,724 | 2026-10-18 | 强制对齐、词级时间戳 |
| [FunASR](https://github.com/modelscope/FunASR) | 20,768 | 2026-10-20 | 模型热词、拼音候选、中文识别与 ONNX 路径 |
| [Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR) | 3,740 | 2026-06-26 | 本地新模型、上下文提示、独立对齐器 |
| [VideoNote / VideoMemo](https://github.com/xiaokeaijqx/VideoNote) | 48 | 2026-06-17 | 新兴笔记方案的 Paraformer / SenseVoice 接入 |

成熟项目优先看 pyVideoTrans、VideoLingo、FunASR。小型 VideoMemo 作为实现补充。KrillinAI 已改名并调整结构，本轮检查的是当前仓库保留的字幕运行时。

## C 源码里真正值得借鉴的做法

**BiliNote：笔记生成并不等于逐字稿纠错。** 本机及上游的 Whisper 路径直接调用 transcribe，再把分段交给笔记提示词。已检查链路未见独立、逐项保留修改的转写校对阶段。相关用户需求也仍值得参考。[转写实现](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/transcriber/whisper.py#L122)、[笔记提示词](https://github.com/JefferyHcool/BiliNote/blob/90940fde4d224d0f69ad99674f4af0a1ea52d3c4/backend/app/gpt/prompt.py)、[用户提出文本修正需求](https://github.com/JefferyHcool/BiliNote/issues/278)。

**pyVideoTrans：纠错是识别后的单独阶段。** 提示词要求保持字幕编号和时间码，并按上下文修正同音字。这种阶段划分值得采用。其提示词也允许整理口吃；本组件应限定为忠实校对，并验证输出没有漏句、添句。[调用位置](https://github.com/jianchang512/pyvideotrans/blob/f9f35d102a2bd7393285eee1e3eaaa69744dab11/videotrans/task/_stage_recogn.py#L111)、[校对提示词](https://github.com/jianchang512/pyvideotrans/blob/f9f35d102a2bd7393285eee1e3eaaa69744dab11/videotrans/prompts/resegment/llm.txt)。

**VideoLingo：术语、断句和对齐各自处理。** 当前本地默认后端已是 Qwen3-ASR，并另用 ForcedAligner 对齐。术语表位于识别之后，主要服务翻译；不能把它当作已经反馈给音频识别的热词机制。语义断句会把分割位置映射回原文。[ASR 后端](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_2_asr.py#L8)、[术语阶段](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_4_1_summarize.py)、[断句映射](https://github.com/Huanshere/VideoLingo/blob/01f843492759be9bbfd1a5cb697b799cc9de1609/core/_3_2_split_meaning.py)。

**KrillinAI：术语替换是明确的文字映射。** 运行时解析用户指定的前后词映射，并在输出阶段另存替换后的文件。它适合确定的专名统一，不会重新听音频，也不能自动判断“猪蹄／主体”的语境。[映射解析](https://github.com/krillinai/OpenCreator/blob/a595282fba72d6594f56b6d4dd928fb3cae72110/runtime/krillinai/internal/service/subtitle_service.go#L57)、[实际替换位置](https://github.com/krillinai/OpenCreator/blob/a595282fba72d6594f56b6d4dd928fb3cae72110/runtime/krillinai/internal/service/upload_subtitle.go#L17)。

**VideoMemo：更换中文引擎是可行思路，对齐能力要单独验收。** 它接入 Paraformer 和 SenseVoice。检查发现，SenseVoice 分支将全文包装为一段，起止时间均为 0。这种结果无法直接用于可靠定位。[实现](https://github.com/xiaokeaijqx/VideoNote/blob/b976105e6812a2e64aff35583534749bd6d63630/backend/app/transcriber/funasr_transcriber.py#L78)。

## D 四种“纠错”机制不能混为一谈

| 机制 | 真正改变什么 | 对本组件的用途 |
|---|---|---|
| 解码时术语提示 | 影响模型听音频时选择词语 | 从视频标题、提问和可信画面词汇提取少量术语 |
| 文本／拼音替换 | 在识别后寻找相近文字并替换 | 生成候选，结合语境判断，避免全局换词 |
| 上下文语义校对 | 根据整段内容判断词语是否合理 | 形成可直接使用的校对稿，保存原文和修改依据 |
| 强制对齐 | 为给定文字估计在音频中的时间位置 | 改变切句或文字粒度后重新定位，不负责证明文字正确 |

FunASR 当前主分支将模型热词与文本后处理明确分开。后处理支持显式词典和拼音相似匹配，并刻意保留原时间戳；它不会重新识别或重新对齐。[后处理实现](https://github.com/modelscope/FunASR/blob/1d066f9d560c9c93100ea6b04582e857930d893b/funasr/utils/postprocess_hotwords.py)、[测试](https://github.com/modelscope/FunASR/blob/1d066f9d560c9c93100ea6b04582e857930d893b/tests/test_postprocess_hotwords.py)。

模型接口也不统一。Fun-ASR-Nano 读取 hotwords；本轮检查的 SenseVoice 路径没有相同的热词使用逻辑。参数能传入不代表会生效。[Nano](https://github.com/modelscope/FunASR/blob/1d066f9d560c9c93100ea6b04582e857930d893b/funasr/models/fun_asr_nano/model.py#L732)、[SenseVoice](https://github.com/modelscope/FunASR/blob/1d066f9d560c9c93100ea6b04582e857930d893b/funasr/models/sense_voice/model.py#L918)。

WhisperX 的核心增益是时间对齐。字词应先校准，再对齐；把错误文字对齐到音频，并不会使它成为正确文字。[WhisperX](https://github.com/m-bain/whisperX/blob/db8fde4d31a3e7f49fe5835938685a76f5ba5477/README.md)、[Qwen 独立对齐器](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B-hf)。

## E 本机轻量探测

本轮沿用组件自己的 Whisper medium、CPU int8。仅对已知错词区间做配对探测，正式配置及完整转写均保持原样。参考术语来自之前查看过的画面，这不是独立音频标注的 CER 基准。

已完成的 161–188 秒区间有三个结果：

| 相同音频区间的设置 | 主体／猪蹄 | 其他观察 | 解码耗时 |
|---|---|---|---:|
| 自动语言＋原视频标题 | 主体 4 次，猪蹄 0 次 | 仍有“单线成、非托普学、狭域、虚实”等词 | 26.550 秒 |
| 指定中文＋原视频标题 | 主体 4 次，猪蹄 0 次 | 本例与自动语言结果一致 | 22.204 秒 |
| 中文＋领域术语提示及 hotwords | 主体 4 次，猪蹄 0 次 | 改善“单线程、辖域、叙事”；仍出现“将死、飞托扑学” | 26.018 秒 |

之前全长转写的相同内容有“猪蹄”。本轮短区间仅沿用原视频标题时已经读对，没有加入新术语表。可以推断解码窗口会影响结果，但还不能据此确定最佳窗口。

术语提示改善了部分词，也新增了“僵死→将死”这类错字。本例同时调整提示文本和 hotwords，不能把增益单独归给其中一个参数。[faster-whisper 参数实现](https://github.com/SYSTRAN/faster-whisper/blob/master/faster_whisper/transcribe.py)。

“移情”和“项目意识”两个 13 秒区间，首个设置均未在子进程 70 秒的实验限内返回。后续两种设置没有继续跑，不能据此比较效果。前一次连续运行也曾在“移情”区间停止而未取得结果，原因尚未定位。全部研究进程已退出，正式转写没有被替换。

本轮只完成了一段音频的三种设置对比，没有完成三段的完整配对评测。原始结果和异常保存在 hint-probe.json。后续正式验收仍需跑完整视频，不能用这组短区间替代。

## F 建议怎样落到组件里

优先交付可追溯的自动校对。当前宿主 Agent 已具备文本和图片理解能力，可以承担语境校对；不必为了这一层再要求一套云服务或笔记生成流程。这是本轮的实现建议。

```flow
全长原始转写 -> 整片语境校对: 宿主Agent
标题与画面词汇 -> 整片语境校对: 带来源的术语
整片语境校对 -> 疑点短窗复听: 需要语音证据时
疑点短窗复听 -> 校对文本: 保留候选和差异
整片语境校对 -> 校对文本
校对文本 -> 自然语言讨论
```

组件应同时保存原始 text、corrected_text 和具体编辑记录。阅读时使用校对稿，追问时能回到原始帧、原始转写与复听结果。它们都是视频材料，不是对宿主的指令。

需要补一个真正的“重新听这个区间”动作。0.4 的区间请求会复用完整 ASR 缓存，普通重读不会重新解码。复听结果应另存，不能污染原始记录。ASR 生成的全部词级时间信息也应保存；目前只留低置信词，限制了后续切句与对齐。

校对时按完整段落理解，再输出最小文字修改。遇到“UR 自选／随机”一类内容冲突，应分别核对原语音、画面和平台字幕；拼音替换无法代替这项判断。

验收继续使用两条完整视频，并增加真实说到“猪蹄、疫情”的反例。比较术语恢复、误改、漏句添句、时间偏移和整条流程耗时。评测参考稿应独立核对，不能把全部参考答案塞进提示词再宣称识别变准。

## G 候选本地模型的优先级

| 候选 | 值得测试的理由 | 本机落地取舍 |
|---|---|---|
| 现有 Whisper medium | 已有完整基线，短窗和术语提示确实会影响结果 | 先接好校对、复听与词级证据 |
| Qwen3-ASR 0.6B，之后视结果测试 1.7B | 支持上下文词汇提示，有独立 ForcedAligner；VideoLingo 已有集成参考 | 下一项新引擎优先候选，先做小批量、分段实测 |
| FunASR contextual Paraformer ONNX | 官方有 CPU 量化运行与热词示例 | 适合作为中文疑点复听候选，需另验时间戳能力 |
| Fun-ASR-Nano | 源码有明确 hotwords 路径，模型卡标注 Apache-2.0 | 与 Qwen 同列后续质量比较，不因名称相似混用参数 |
| 中文微调 Belle Whisper | 可继续利用 Whisper 系实现；VideoLingo 的 WhisperX 路径使用它 | 可作保留 CTranslate2 路线的对照，但权重更大 |

Qwen 的 qwen-asr SDK 用 context；原生 Transformers 模型卡示例用 prompt。需要按具体入口接入。[官方本地仓库](https://github.com/QwenLM/Qwen3-ASR/blob/7c6daf77a2421100f5fb066495372c00129d39ff/qwen_asr/inference/qwen3_asr.py)、[原生模型卡](https://huggingface.co/Qwen/Qwen3-ASR-0.6B-hf#context--hotwords)。

新模型的热词也有过度偏置风险。Qwen 官方问题区有用户报告提示词混入转写、弱语音被改成提示词；这是用户报告，本轮没有下载该模型复现。[问题 #186](https://github.com/QwenLM/Qwen3-ASR/issues/186)。

CPU 量化和热词参考来自 [FunASR ONNX 文档](https://github.com/modelscope/FunASR/blob/1d066f9d560c9c93100ea6b04582e857930d893b/runtime/python/onnxruntime/README.md)、[contextual 示例](https://github.com/modelscope/FunASR/blob/1d066f9d560c9c93100ea6b04582e857930d893b/runtime/python/onnxruntime/demo_contextual_paraformer.py)。其他权重依据 [Nano 模型卡](https://huggingface.co/FunAudioLLM/Fun-ASR-Nano-2512)、[Belle 模型卡](https://huggingface.co/BELLE-2/Belle-whisper-large-v3-zh-punct)。

本机现有 GPU 运行环境仍未通过实际解码检查，不能承诺 8 GB 显存下的速度或可用性。Qwen 的模型与对齐器可考虑分时加载；实际峰值显存和 Windows 兼容性留待引擎试验。本轮没有安装新模型。

## H 调查范围与保存内容

正式组件保持 0.4，本轮完成源码调查和隔离实验。研究材料保存到组件自己的 research/asr-correction-20261021 目录。

project-snapshot.json 保存 8 个项目的现场元数据、提交号和 36 份参考源码／文档。hint-probe.json 保存探测参数、完整结果和异常。参考源码仅作为研究材料，不导入、不执行，也不成为组件运行依赖。

当前项目元数据显示：BiliNote、FunASR 为 MIT，VideoLingo、OpenCreator、VideoMemo、Qwen3-ASR 为 Apache-2.0，WhisperX 为 BSD-2-Clause，pyVideoTrans 为 GPL-3.0。可借鉴流程并自行实现；若引入源码或权重，应按具体版本保留对应许可。

模型许可须逐个核对。FunASR 仓库还有独立 MODEL_LICENSE，不能把框架的 MIT 许可直接覆盖到所有权重上。[模型协议原文](https://github.com/modelscope/FunASR/blob/1d066f9d560c9c93100ea6b04582e857930d893b/MODEL_LICENSE)。
