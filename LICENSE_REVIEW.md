# 许可证核对与适用范围

身份：按阶段保留的许可核对记录，不是整个运行目录可公开分发的许可结论。下文早期 Qwen“仅实验、未接正式入口”描述当时阶段；0.6.2 已接显式可选来源，复用组件内隔离环境，见[第三方声明](THIRD_PARTY_NOTICES.md)及[当前接入参考](docs/reader-reference.md#可选-qwen)。新代码对外许可及发布清单仍待选择。

## 2026-10-21：基础发现与隔离 ASR 实验

0.6 新增检索/热门逻辑使用标准库与既有组件登录，没有新增正式运行依赖。设备标识、WBI 参数及置换表作为平台协议数据使用，参考已安装 yt-dlp 2026.08.19 的 Bilibili 实现（Unlicense），未复制其他应用业务模块。

Qwen3-ASR 0.6B 仅安装于独立研究环境，权重位于组件 models 内。官方模型卡标注 Apache-2.0，固定 revision 与权重 SHA-256 在模型 `model-provenance.json`。Qwen 官方 Apache-2.0 文本和实验 Python 包随附许可保存在 `research/asr-engine-20261021/licenses/`，逐包元数据在相邻 `packages-license-inventory.json`。PyTorch、torchaudio 及各附属库沿用自己的许可，不能用 Qwen 的顶层许可覆盖。没有将实验环境、权重或服务变为正式阅读入口的依赖。

## 2026-10-21：本地 OCR 与完整语音处理

新增 rapidocr-onnxruntime 1.4.4，包许可为 Apache-2.0；随 wheel 的 PP-OCR 模型来自 Apache-2.0 的 PaddleOCR 系列。保留安装包原始许可、来源和模型 SHA-256。新增 OpenCV 5.0.0.93、pyclipper 1.4.0、Shapely 2.2.0、six 1.17.0 的实际 wheel 许可继续逐包保存；不以顶层包许可替代附属库声明。这里的依据为 PyPI 1.4.4 版本页、wheel 元数据与随包许可。该包较新的发行版本并未用于本次实现。

OCR 在本机执行，没有引入云端 OCR 服务。新写的完整区间覆盖、按词边界归属、动画局部观察和可追溯文字校验代码没有复制其他应用的业务实现。

本次保留已验证的 MIT 组件并完成独立封装，没有为了目录独立而重写抽帧算法。新实现不导入或启动 watch、BiliNote 的安装内容，也不读取它们的配置。

| 范围 | 已核对许可 | 本次处理 |
|---|---|---|
| 内嵌 watch / claude-video 0.3.2 的 frames、runtime、transcribe、gemini | MIT，Bradley Bonanno | 保留源码与完整版权许可；删除原来的外部配置发现模块。导入和错误提示有少量适配 |
| faster-whisper | MIT，SYSTRAN | 独立虚拟环境安装，保留 wheel 中的许可 |
| Whisper medium 权重及 Systran 转换 | 官方模型卡标注 MIT；OpenAI Whisper 项目许可 MIT | 复制四个模型文件，保存上游模型卡、MIT 原文及模型哈希校验 |
| MCP Python SDK、CTranslate2 等 Python 依赖 | 以各项目/wheel 许可为准，主要为 MIT/BSD/Apache 等 | 保留安装的 license 文件，并生成逐包版本/许可清单；不将整个目录一概标为 MIT |
| PyAV 16.1.0 | PyAV 接口 BSD-3-Clause；wheel 内附 FFmpeg 等库另有许可 | 原始 wheel 元数据及相关许可证均保留在虚拟环境和 `licenses/python-packages/` |
| 本机 Python | PSF 及 Python 随附第三方许可 | 公共运行环境，不复制解释器；记录依赖 |
| 本机 FFmpeg 8.1.1 Gyan full build | 实际 `ffmpeg -L` 输出 GPLv3-or-later，构建含 `--enable-gpl --enable-version3` | 作为公共独立程序调用，不把该可执行文件复制进组件；保存其许可及构建说明供查阅 |
| yt-dlp Python 源码包 | Unlicense；附属依赖另有许可 | 本组件自己的环境内安装固定版本；保留许可及依赖清单 |
| 本机 Node 24.15.0 | Node 本体 MIT，附属第三方许可见其完整 LICENSE | 公共运行环境，不复制可执行文件；保存完整许可供查阅 |

新增业务代码尚未指定对外发布的统一许可证；这不影响当前用户在本机保存、修改和使用。此目录中的第三方源码、模型、wheels 继续按各自许可保留。若以后公开分发含模型、虚拟环境或二进制的整包，应按实际分发内容处理对应许可，不能仅给整个目录贴 MIT 标签。

BiliNote 的业务代码没有被复制或导入；这里只从本机已有副本取得与官方哈希一致的 Whisper 模型文件，许可依据模型上游，而非笔记应用的许可。

核对来源：

- [watch 的 MIT 原文](https://github.com/bradautomates/claude-video/blob/main/LICENSE)
- [faster-whisper 的 MIT 原文](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE)
- [Systran 模型卡与 MIT 标注](https://huggingface.co/Systran/faster-whisper-medium/blob/main/README.md)
- [OpenAI Whisper 许可](https://github.com/openai/whisper/blob/main/LICENSE)
- [FFmpeg 官方许可说明](https://ffmpeg.org/legal.html)；本机实际构建输出另存
- [yt-dlp 许可](https://github.com/yt-dlp/yt-dlp/blob/2026.08.19/LICENSE)
- [Python 许可](https://docs.python.org/3.12/license.html)
- [Node 24.15.0 完整许可](https://github.com/nodejs/node/blob/v24.15.0/LICENSE)

上游原文与逐包清单分别保存在 `licenses/upstream/`、`licenses/python-packages.json`。模型具体版本和文件 SHA-256 在 `models/faster-whisper-medium/model-provenance.json`。

## 2026-10-21：Qwen 对齐及独立参考

官方 Qwen3-ForcedAligner-0.6B，revision `c7cbfc2048c462b0d63a45797104fc9db3ad62b7`，模型卡标明 Apache-2.0。权重 SHA-256 `47831d0e82f96b20e9034dba01a075ee06436654719f6a68289e49f1b65ce0e7` 与官方 LFS 相符；许可原文沿用组件内 Qwen 官方 Apache 文本。仅调用已经安装的官方 SDK，没有复制其模型代码或增加正式运行依赖。

独立参考来自 Google/FLEURS 团队发布的 FLEURS，许可 CC-BY-4.0。固定 revision `70bb2e84b976b7e960aa89f1c648e09c59f894dd` 的 cmn_hans_cn test，原始 README、TSV、音频归档及哈希保留。参考音频不修改；切分压力样本明确记录了拼接、重复和插入静音。归属、许可链接与使用变更见 THIRD_PARTY_NOTICES.md 及研究 README。没有新增包，先前隔离环境中的包保留各自许可。

## 2026-10-21：独立扫码登录与续期

`video_reader/bilibili_auth.py` 为本组件新写的实现，没有复制或导入所调查应用的业务代码。登录/续期协议依据公开接口研究核对，B 站 RSA 公钥作为协议数据使用。新增本地二维码依赖 qrcode 8.2，随安装包许可为 BSD-3-Clause。RSA-OAEP 使用组件环境内已有的 cryptography 50.0.2，许可为 Apache-2.0 OR BSD-3-Clause；现已将其列入直接依赖。安装包原始许可继续保留。
