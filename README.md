# OratorDeck

> Generate a narrated video with underlined visual anchors—plus separate,
> matching timed subtitle files—so you can prepare a slide presentation faster.

[English](#english) · [简体中文](#简体中文)

<a id="english"></a>

## English

### What does OratorDeck do?

OratorDeck turns a slide presentation into a complete narrated video. Each
slide stays on screen while its narration plays, and successfully located
visible phrases are underlined at the moment they are spoken. Matching timed
subtitles are delivered as separate SRT, WebVTT, and LRC files.

The result is useful for rehearsing, reviewing, sharing, or publishing a
presentation without manually recording and editing every slide.

OratorDeck is intentionally split into two independent, composable parts:

1. **Prompt-first authoring:** the optional skill turns per-slide prompts into
   aligned slide images and synchronized speaker notes. It does not require the
   local media runtime or a local GPU.
2. **Standalone media generation:** the repository workflow turns prepared
   images and speaker notes into audio, subtitles, and the annotated video. It
   does not require the skill or an Agent once those inputs exist.

Use either part by itself, or run them in sequence.

### Option 1: Start from per-slide prompts

This is the easiest option when you are still preparing the presentation.
Create one self-contained Markdown prompt per slide:

```text
resources/
├── slide-01_opening.md
├── slide-02_problem.md
├── slide-03_method.md
└── ...
```

Each prompt should describe the slide's purpose, content, layout, and exact
visible wording. If you only have an outline, the skill can help write these
prompts first.

Install the
[`oratordeck-prompt-first`](skills/oratordeck-prompt-first) skill from:

```text
https://github.com/yuminhhuang/OratorDeck/tree/main/skills/oratordeck-prompt-first
```

For images and speaker notes only—even on a device without a local GPU—ask
Codex:

```text
Use $oratordeck-prompt-first with my per-slide prompts to generate the slide
images and synchronized English speaker notes.
```

The skill stops after preparing and auditing the prompts, matching images, and
speaker notes. It does not install or run TTS, transcription, OCR video
rendering, or FFmpeg. You remain in control of facts, numbers, citations, and
other source material.

Image creation requires an image-generation capability available to the agent.
The skill does not require a GPU on the user's device. If image generation is
unavailable, the skill can still help author and audit the prompts. Its bundled
audits use only the Python 3 standard library and work on Linux, macOS, and
Windows.

When the OratorDeck media runtime and a suitable GPU are already available, you
can ask the Agent to continue after the skill finishes:

```text
After the slide images and speaker notes pass their audit, continue outside the
skill by running scripts/generate-keynote-workflow.sh to produce the final
media.
```

Without that extra request, the skill ends with the images and speaker notes.

### Option 2: Start from your own images and speaker notes

This is the independent media-generation half. Neither the skill nor an Agent
is required once you have prepared these two inputs:

```text
resources/
├── SPEAKER_NOTES.md
└── generated-images/
    ├── slide-01_opening.png
    ├── slide-02_problem.png
    └── ...
```

You are responsible for ensuring that each image and its narration describe
the same content.

Write one section per slide in `SPEAKER_NOTES.md`:

```markdown
## Slide 01 - Opening

**Target time:** 0:45

Welcome to the presentation. We will begin with the **central question** and
then build the evidence step by step.
```

The bold phrase is spoken normally. If the same phrase is visible and legible
in the slide image, OratorDeck tries to locate and underline it when it is
spoken. Any unresolved anchors are recorded in the run report.

Slide numbers must be contiguous and agree across the notes and images.
Supported image names include `slide-01.png`, `slide-01-opening.jpg`, and
`slide-01_opening.webp`.

### Install the local media runtime

Skip this section if you only want the skill to create images and speaker
notes. For local audio and video generation, Python 3.11 and a CUDA-capable
NVIDIA GPU are recommended. Git and [`just`](https://github.com/casey/just)
are also required to prepare Voicebox.

```bash
git clone https://github.com/yuminhhuang/OratorDeck.git
cd OratorDeck

python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

scripts/setup-voicebox.sh
```

Follow the command printed by `setup-voicebox.sh` to install the Voicebox
backend. Then start the local service:

```bash
ORATORDECK_TTS_GPU=0 scripts/run-voicebox.sh
```

With the service running, create a Qwen CustomVoice profile in Voicebox. See
the [installation guide](docs/installation.md) for the complete Voicebox and
voice-profile setup.

### Run the standalone media workflow

Whether the assets came from the skill or were prepared manually, edit
`scripts/generate-keynote-workflow.sh` and set the voice profile, GPU, output
name, and any timing preferences. Then run:

```bash
scripts/generate-keynote-workflow.sh
```

### What will the full media workflow produce?

Each run is saved in one timestamped directory:

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

The main deliverable is `video/my-talk.mp4`. You also receive the complete
audio, separate subtitle files, one audio/video file per slide, a snapshot of
the inputs, timing information, anchor results, and the full generation log.

### Current limitations

- The standalone media workflow currently targets English narration.
- Slide backgrounds are static images; underlined anchors provide the visual
  emphasis.
- Timed subtitles are separate SRT, WebVTT, and LRC files. They are not
  currently burned into or embedded in the MP4.
- An anchor can only be underlined when its text is visible and legible in the
  image.
- Target durations are goals. The selected voice may speak faster or slower
  than requested.
- Generated slides, narration, subtitles, and anchors should be reviewed before
  publication.
- Model weights are downloaded separately and remain subject to their own
  licenses and terms.

### For developers

The implementation stages, data contracts, report formats, validation
strategy, repository layout, and roadmap are documented separately in the
[technical architecture](docs/architecture.md#english).

### Responsible use

Use only voices and source material that you own or have permission to use.
OratorDeck is intended to assist authorship, not to impersonate people or hide
the origin of synthetic media.

### Acknowledgements

OratorDeck is built on an excellent open-source ecosystem. Special thanks to:

- [Voicebox](https://github.com/jamiepine/voicebox) and its contributors for
  the local voice studio and inference API.
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) for the speech models used
  by the current narration workflow.
- [OpenAI Whisper](https://github.com/openai/whisper) and
  [Hugging Face Transformers](https://github.com/huggingface/transformers) for
  speech recognition and model tooling.
- [RapidOCR](https://github.com/RapidAI/RapidOCR) for locating visible anchor
  text.
- [FFmpeg](https://ffmpeg.org/) and
  [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) for media
  encoding and assembly.
- [PyTorch](https://github.com/pytorch/pytorch),
  [FlashAttention](https://github.com/Dao-AILab/flash-attention),
  [NumPy](https://github.com/numpy/numpy),
  [python-soundfile](https://github.com/bastibe/python-soundfile), and
  [Pillow](https://github.com/python-pillow/Pillow) for local inference and
  media processing.

OratorDeck is an independent project and is not endorsed by or affiliated with
these upstream projects.

### License

OratorDeck is released under the [MIT License](LICENSE). Runtime libraries and
model weights retain their own licenses and terms. See
[Third-Party Notices](THIRD_PARTY_NOTICES.md).

---

<a id="简体中文"></a>

## 简体中文

### OratorDeck 能做什么？

OratorDeck 通过生成带视觉锚点下划线的演讲视频，并同时提供匹配的定时字幕文件，帮助你
更快准备幻灯片演示。视频播放一张 slide 的讲稿时，会保持该 slide 作为背景，并在读到
成功定位的可见短语时为其添加下划线；定时字幕则以独立的 SRT、WebVTT 和 LRC 文件提供。

这样的结果可用于演练、审阅、分享或发布演示，无需手工录制和剪辑每张 slide。

OratorDeck 刻意分为两个相互独立、又可组合使用的部分：

1. **Prompt-first 创作：**可选 skill 把逐页 prompts 转换为相互对齐的 slide 图片和同步
   讲稿，不要求本地媒体环境或本地 GPU。
2. **独立媒体生成：**仓库工作流把准备好的图片和讲稿转换为音频、字幕和标注视频。输入
   准备好后，这一部分不要求 skill 或 Agent。

你可以单独使用任意一部分，也可以依次串联使用。

### 方式一：从逐页 prompts 开始

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
[`oratordeck-prompt-first`](skills/oratordeck-prompt-first) skill：

```text
https://github.com/yuminhhuang/OratorDeck/tree/main/skills/oratordeck-prompt-first
```

如果只需要图片和讲稿——即使设备没有本地 GPU——可以告诉 Codex：

```text
Use $oratordeck-prompt-first with my per-slide prompts to generate the slide
images and synchronized English speaker notes.
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

### 方式二：使用自己的图片和讲稿

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

### 安装本地媒体环境

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

### 运行独立媒体工作流

无论图片和讲稿来自 skill 还是由用户手工准备，都可以编辑
`scripts/generate-keynote-workflow.sh`，设置声音 profile、GPU、输出名称和时间参数，
然后运行：

```bash
scripts/generate-keynote-workflow.sh
```

### 完整媒体工作流会生成什么？

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

### 当前限制

- 当前独立媒体工作流面向英文演讲。
- Slide 背景是静态图片；下划线锚点用于提供视觉强调。
- 定时字幕以独立的 SRT、WebVTT 和 LRC 文件提供，当前不会烧录或封装进 MP4。
- 只有当锚点文字在图片中清晰可见时，才能准确添加下划线。
- 预期时长是目标值；实际语速可能快于或慢于要求。
- 发布前应人工检查生成的 slide、讲稿、字幕和锚点。
- 模型权重单独下载，并分别受自身许可证和条款约束。

### 开发者文档

实现阶段、数据契约、报告格式、验证策略、仓库结构和路线图统一收录在独立的
[技术架构文档](docs/architecture.md#简体中文)中。

### 负责任地使用

只使用你拥有或已获授权的声音与材料。OratorDeck 用于辅助创作，不应用于冒充他人或隐藏
合成媒体的来源。

### 致谢

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

### 许可证

OratorDeck 使用 [MIT License](LICENSE) 发布。运行依赖和模型权重仍受各自许可证与条款
约束。详见[第三方声明](THIRD_PARTY_NOTICES.md)。
