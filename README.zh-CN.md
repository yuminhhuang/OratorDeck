# OratorDeck

> 生成带视觉锚点下划线的演讲视频，并提供匹配的独立定时字幕文件，帮助你更快准备
> 幻灯片演示。

![OratorDeck 最终效果：演讲视频在读到视觉锚点时添加下划线，并提供独立的定时字幕文件](docs/assets/oratordeck-final-effect.png)

[English](README.md) · [简体中文](README.zh-CN.md)

## OratorDeck 能做什么？

OratorDeck 通过生成带视觉锚点下划线的演讲视频，并同时提供匹配的定时字幕文件，帮助你
更快准备幻灯片演示。视频播放一张 slide 的讲稿时，会保持该 slide 作为背景，并在读到
成功定位的可见短语时为其添加下划线；定时字幕则以独立的 SRT、WebVTT 和 LRC 文件提供。

这样的结果可用于演练、审阅、分享或发布演示，无需手工录制和剪辑每张 slide。

OratorDeck 刻意分为两个相互独立、又可组合使用的部分：

1. **Skill 辅助创作：**可选的 `$oratordeck` skill 把逐页 prompts 转换为相互对齐的
   slide 图片和同步讲稿，不要求本地媒体环境或本地 GPU。
2. **独立媒体生成：**仓库工作流把准备好的图片和讲稿转换为音频、字幕和标注视频。输入
   准备好后，这一部分不要求 skill 或 Agent。

你可以单独使用任意一部分，也可以依次串联使用。

## OratorDeck 适合你吗？

可以根据主要目标快速选择：

| 你的主要目标 | 更合适的起点 |
| --- | --- |
| 使用相互对齐的 slide 图片和讲稿制作长篇英文演讲，并在读到可见短语时为其添加下划线 | **OratorDeck** |
| 现在用 prompts 创建 slide 图片和同步讲稿，稍后或换一台设备再生成媒体 | 可选的 **OratorDeck skill** |
| 通过 GUI 或 Agent 制作并手工调整原生、可编辑的 PPTX | [Presenton](https://github.com/presenton/presenton) 或 [PPT Master](https://github.com/hugohe3/ppt-master) |
| 从研究论文 PDF 直接生成带烧录字幕和区域视觉提示的短篇研究视频 | [ResearchStudio Paper2Video](https://github.com/microsoft/ResearchStudio/tree/main/ResearchStudio-Reel/skills/paper2video) |
| 只需自动生成 presentation deck，不需要配音或标注视频 | [Presenton](https://github.com/presenton/presenton)、[PPT Master](https://github.com/hugohe3/ppt-master) 或 [PPTAgent](https://github.com/icip-cas/PPTAgent) |

OratorDeck 是专注于演讲视频的命令行工作流，不是通用 PowerPoint 编辑器，也不是一键式
论文摘要工具。当你重视长篇讲稿、逐页时间、独立字幕文件和精确文字锚点的控制时，它会
比较合适。完整的本地媒体工作流目前面向 Python 3.11 和 NVIDIA CUDA GPU；它不会生成
可编辑 PPTX，字幕也以独立文件提供，而不是烧录进视频。

这些工具并不互斥。你可以在其他工具中制作 deck，再导出 slide 图片，并把讲稿整理为
OratorDeck 的输入格式。没有本地 GPU 的设备也可以只使用 OratorDeck 的 Skill 辅助
创作部分。

## 方式一：从逐页 prompts 开始

当你还在准备演示内容时，这是最简单的方式。为每张 slide 创建一份自包含的 Markdown
prompt：

```text
resources/
├── slide-01_opening.md
├── slide-02_problem.md
├── slide-03_method.md
└── ...
```

每份 prompt 应描述该页的目的、内容、布局和需要准确显示的文字。如果手中只有大纲，
skill 也可以先帮助你编写这些 prompts。

从以下地址安装
[`oratordeck`](skills/oratordeck) skill：

```text
https://github.com/yuminhhuang/OratorDeck/tree/main/skills/oratordeck
```

如果只需要图片和讲稿——即使设备没有本地 GPU——可以告诉 Codex：

```text
Use $oratordeck with my per-slide prompts to generate the slide images and
synchronized English speaker notes.
```

skill 会在准备并审查 prompts、对应图片和讲稿后结束。它不会安装或运行 TTS、语音转录、
OCR 视频渲染或 FFmpeg。事实、数字、引用及其他源材料仍由用户控制。

自动创建图片要求 Agent 具备图片生成能力，但 skill 不要求用户设备具备 GPU。如果无法
生成图片，skill 仍可帮助编写和审查 prompts。它附带的审查工具只使用 Python 3 标准库，
可在 Linux、macOS 和 Windows 上运行。

如果设备已经准备好 OratorDeck 媒体环境和合适的 GPU，可以要求 Agent 在 skill 完成后
继续：

```text
After the slide images and speaker notes pass their audit, continue outside the
skill by running scripts/generate-keynote-workflow.sh to produce the final
media.
```

如果没有这项额外要求，skill 会停在图片和讲稿。

## 方式二：使用自己的图片和讲稿

这是独立的媒体生成部分。准备好以下两份输入后，既不要求安装 skill，也不要求使用
Agent：

```text
resources/
├── SPEAKER_NOTES.md
└── generated-images/
    ├── slide-01_opening.png
    ├── slide-02_problem.png
    └── ...
```

用户需要自行保证每张图片与对应讲稿表达相同内容。

在 `SPEAKER_NOTES.md` 中为每张 slide 编写一个 section：

```markdown
## Slide 01 - Opening

**Target time:** 0:45

Welcome to the presentation. We will begin with the **central question** and
then build the evidence step by step.
```

加粗短语会被正常朗读。如果相同短语清晰显示在 slide 图片中，OratorDeck 会尝试定位并
在读到它时添加下划线；无法定位的锚点仍会记录在运行报告中。

讲稿和图片中的 slide 编号必须连续且一致。图片可以命名为 `slide-01.png`、
`slide-01-opening.jpg` 或 `slide-01_opening.webp`。

## 安装本地媒体环境

如果只使用 skill 创建图片和讲稿，可以跳过本节。要在本地生成音频和视频，建议使用
Python 3.11 和支持 CUDA 的 NVIDIA GPU；准备 Voicebox 还需要 Git 和
[`just`](https://github.com/casey/just)。

```bash
git clone https://github.com/yuminhhuang/OratorDeck.git
cd OratorDeck

python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

scripts/setup-voicebox.sh
```

按照 `setup-voicebox.sh` 输出的命令安装 Voicebox backend，然后启动本地服务：

```bash
ORATORDECK_TTS_GPU=0 scripts/run-voicebox.sh
```

服务启动后，再在 Voicebox 中创建 Qwen CustomVoice profile。完整配置方式见
[安装指南](docs/installation.md)。

## 运行独立媒体工作流

无论图片和讲稿来自 skill 还是由用户手工准备，都可以编辑
`scripts/generate-keynote-workflow.sh`，设置声音 profile、GPU、输出名称和时间参数，
然后运行：

```bash
scripts/generate-keynote-workflow.sh
```

## 完整媒体工作流会生成什么？

每次运行都保存在一个带时间戳的目录中：

```text
data/runs/my-talk-YYYYMMDD-HHMMSS/
├── input/
│   ├── SPEAKER_NOTES.md
│   ├── SPEAKER_NOTES_CHUNKS.json
│   ├── SPEAKER_NOTES_TTS.txt
│   └── generated-images/
├── audio/
│   ├── my-talk.wav
│   ├── my-talk.timing.json
│   └── my-talk.chunks/
├── subtitles/
│   ├── my-talk.srt
│   ├── my-talk.vtt
│   └── my-talk.lrc
├── video/
│   ├── clips/
│   ├── anchor-video-report.json
│   └── my-talk.mp4
└── workflow.log
```

主要结果是 `video/my-talk.mp4`。此外还会得到完整音频、独立字幕文件、逐页音频和视频、
输入快照、时间信息、锚点结果以及完整生成日志。

## 当前限制

- 当前独立媒体工作流面向英文演讲。
- Slide 背景是静态图片；下划线锚点用于提供视觉强调。
- 定时字幕以独立的 SRT、WebVTT 和 LRC 文件提供，当前不会烧录或封装进 MP4。
- 只有当锚点文字在图片中清晰可见时，才能准确添加下划线。
- 预期时长是目标值；实际语速可能快于或慢于要求。
- 发布前应人工检查生成的 slide、讲稿、字幕和锚点。
- 模型权重单独下载，并分别受自身许可证和条款约束。

## 开发者文档

实现阶段、数据契约、报告格式、验证策略、仓库结构和路线图统一收录在独立的
[技术架构文档](docs/architecture.md#简体中文)中。

## 负责任地使用

只使用你拥有或已获授权的声音与材料。OratorDeck 用于辅助创作，不应用于冒充他人或隐藏
合成媒体的来源。

## 致谢

OratorDeck 建立在优秀的开源生态之上。特别感谢：

- [Voicebox](https://github.com/jamiepine/voicebox) 及其贡献者提供本地语音工作室和
  推理 API。
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) 提供当前朗读流程使用的语音模型。
- [OpenAI Whisper](https://github.com/openai/whisper) 与
  [Hugging Face Transformers](https://github.com/huggingface/transformers)
  提供语音识别和模型工具。
- [RapidOCR](https://github.com/RapidAI/RapidOCR) 用于定位可见锚点文字。
- [FFmpeg](https://ffmpeg.org/) 与
  [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) 用于媒体编码与合成。
- [PyTorch](https://github.com/pytorch/pytorch)、
  [FlashAttention](https://github.com/Dao-AILab/flash-attention)、
  [NumPy](https://github.com/numpy/numpy)、
  [python-soundfile](https://github.com/bastibe/python-soundfile) 和
  [Pillow](https://github.com/python-pillow/Pillow) 提供本地推理和媒体处理能力。

OratorDeck 是独立项目，不代表上述上游项目，也未获得其官方背书。

## 许可证

OratorDeck 使用 [MIT License](LICENSE) 发布。运行依赖和模型权重仍受各自许可证与条款
约束。详见[第三方声明](THIRD_PARTY_NOTICES.md)。
