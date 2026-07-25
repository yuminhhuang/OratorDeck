# OratorDeck

> Quickly prepare a deck talk by generating a narrated video with timed
> captions and underlined visual anchors.

[English](#english) · [简体中文](#简体中文)

<a id="english"></a>

## English

### What is OratorDeck?

OratorDeck helps users quickly prepare deck presentations by generating
narrated videos with timed captions and underlined visual anchors. Each slide
serves as a static background, and its visible anchor phrases are underlined as
they are spoken.

There are two ways to use it:

1. **Prompt-first skill:** provide one prompt per slide; the skill generates the
   slide images and synchronized speaker notes, then runs the complete video
   workflow.
2. **Standalone core pipeline:** provide your own speaker notes and slide
   images, guarantee that they agree, and run the video workflow directly.

### 1. Prompt-first skill: prompts to finished video

This is the recommended path when the deck is still being authored. Install
[`oratordeck-prompt-first`](skills/oratordeck-prompt-first), then prepare one
self-contained Markdown prompt for every slide:

```text
resources/
├── slide-01_opening.md
├── slide-02_problem.md
├── slide-03_method.md
└── ...
```

Each file states the slide's role, audience takeaway, and a fenced
image-generation prompt; every intended visible label is written exactly in
double quotes. See the skill's
[prompt contract](skills/oratordeck-prompt-first/references/prompt-contract.md)
for the complete template.

Those prompts are the authoritative deck sources. From them, the skill:

1. validates the slide argument, visible wording, reading order, and claim
   boundaries;
2. generates one matching 16:9 image per prompt;
3. derives timed speaker notes from the same prompts;
4. reuses visible slide wording as spoken bold anchors;
5. audits prompt, image, note, and anchor coverage;
6. runs TTS, subtitle generation, OCR matching, per-slide rendering, and final
   video assembly.

```text
per-slide Markdown prompts
            │
            ▼
  OratorDeck prompt-first skill
            │
            ├──> aligned slide images
            └──> timed notes + spoken anchors
                         │
                         ▼
             OratorDeck media pipeline
                         │
                         ▼
       narrated, captioned, anchor-annotated MP4
```

In other words, once the per-slide prompts are ready, the skill can carry the
deck through to the finished video in one guided workflow. If you only have a
presentation brief, the skill can also help design the prompts first.

Ask Codex to install the skill directly from:

```text
https://github.com/yuminhhuang/OratorDeck/tree/main/skills/oratordeck-prompt-first
```

Or copy it into your Codex skills directory:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/oratordeck-prompt-first "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Then invoke it, for example:

```text
Use $oratordeck-prompt-first with my per-slide prompts to generate the slide
images, synchronized English speaker notes, and final annotated video.
```

The skill needs an image-generation capability to render the slides and uses
the local OratorDeck runtime described below for media production. It does not
invent missing evidence, metrics, citations, or other factual content.

### 2. Standalone core pipeline: your notes and images

The skill is not required. You can use OratorDeck directly by preparing:

- `resources/SPEAKER_NOTES.md` — narration, target duration, and bold visual
  anchors for every slide;
- `resources/generated-images/` — one rendered image for every narrated slide.

In this mode, **you are responsible for ensuring that the notes and images
describe the same content**. OratorDeck preserves that alignment during media
generation, but does not infer or repair semantic inconsistencies between the
two inputs.

#### Speaker-note contract

Speaker notes use one section per slide:

```markdown
## Slide 01 - Opening

**Target time:** 0:45

Welcome to the presentation. We will begin with the **central question** and
then build the evidence step by step.
```

The corresponding image can be named `slide-01.png`,
`slide-01-opening.jpg`, or `slide-01_opening.webp`. Exactly one matching image
must exist for each narrated slide.

The current contract is deliberately simple:

1. Slide numbers are contiguous and agree across the notes and images.
2. Each slide contains exactly one `**Target time:** M:SS` field.
3. Bold phrases are spoken normally and act as annotation anchors.
4. A bold anchor should also appear as visible text in the corresponding slide
   image if it is expected to be underlined.
5. The user is responsible for the semantic consistency of the two inputs.

Target durations are goals rather than guarantees. Natural speech, model
behavior, and the configured timing tolerance determine the final duration.

#### Install and run the core pipeline

Use Python 3.11, install the OratorDeck dependencies, then prepare the pinned
Voicebox backend:

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

scripts/setup-voicebox.sh
# Follow the printed Voicebox backend installation command, then:
ORATORDECK_TTS_GPU=0 scripts/run-voicebox.sh
```

See the full [installation guide](docs/installation.md), including creation of
a Qwen CustomVoice profile.

Copy the speaker-note template, add the matching slide images, and edit the
intentionally transparent workflow script:

```bash
cp resources/SPEAKER_NOTES.example.md resources/SPEAKER_NOTES.md
scripts/generate-keynote-workflow.sh
```

Users edit the input paths, voice profile, batch size, timing tolerance, GPU
selection, and output name directly in that file.

### What the media pipeline does

- Keeps each slide as **one indivisible unit** for authorship, TTS, timing,
  diagnosis, and rendering.
- Batches complete slide chunks for GPU throughput without splitting one
  slide's narration.
- Produces one WAV per slide, a joined keynote WAV, and a machine-readable
  timing report.
- Uses Whisper timestamps for captions and optional manuscript-based wording
  correction.
- Treats **bold phrases** in the notes as visual anchors.
- Locates those phrases in the slide image with OCR and underlines them when
  they are spoken.
- Renders one static-background clip per slide and concatenates the clips into
  the final MP4.

```text
SPEAKER_NOTES.md ──> slide chunks ──> batched TTS ──> slide WAVs
       │                                      │
       │                                      └──> timing report
       │
       └──> bold anchors

joined WAV ──> Whisper timestamps ──> manuscript-corrected subtitles

slide images ──> OCR positions ─┐
bold anchors ───────────────────┼──> timed underlines ──> slide clips ──> MP4
timing/subtitles ───────────────┘
```

### Run output

Every run is kept in one timestamped directory:

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
│   ├── my-talk.raw.srt
│   ├── my-talk.srt
│   ├── my-talk.vtt
│   └── my-talk.lrc
├── video/
│   ├── slides/
│   ├── annotation-report.json
│   └── my-talk.mp4
└── workflow.log
```

Generated media, model weights, caches, the patched Voicebox checkout, local
environments, logs, and private presentation materials are excluded from source
control.

### Current scope and limitations

- The production path currently targets English narration.
- A CUDA-capable NVIDIA GPU is recommended for practical TTS and transcription
  throughput.
- Slide backgrounds are static images; the timed underlines are the current
  visual annotation mechanism.
- OCR can only locate text that is visible and sufficiently legible in the
  rendered slide image.
- Subtitle timing improves anchor synchronization, but proportional timing is
  available as a fallback.
- OratorDeck does not currently verify that the notes and images make the same
  factual claims.
- Model weights are downloaded separately and remain subject to their own
  licenses and terms.

### Roadmap

- [x] Publish the sanitized, reproducible source distribution.
- [ ] Add a project-level configuration schema while keeping the workflow
  script easy to edit.
- [x] Package the prompt-first workflow as an optional installable agent skill.
- [x] Accept structured LLM prompts describing a presentation.
- [x] Generate matched slide images and speaker notes from the same prompt
  representation.
- [ ] Validate visual–narrative consistency before synthesis.
- [ ] Support pluggable image, TTS, transcription, and OCR backends.
- [ ] Add resumable per-slide generation and richer annotation styles.

### Responsible use

Use only voices and source material that you own or have permission to use.
Review generated narration, captions, and visual annotations before publishing
the final video. OratorDeck is intended to assist authorship, not to conceal the
origin of synthetic media or impersonate people without consent.

### Acknowledgements

OratorDeck is possible because of a generous open-source ecosystem. Special
thanks to:

- [Voicebox](https://github.com/jamiepine/voicebox), created by Jamie Pine and
  its contributors, for the local voice studio and inference API on which the
  current TTS workflow is built.
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) and the Qwen team for the
  speech models used by the current narration path.
- [OpenAI Whisper](https://github.com/openai/whisper) and
  [Hugging Face Transformers](https://github.com/huggingface/transformers) for
  speech recognition and model tooling.
- [RapidOCR](https://github.com/RapidAI/RapidOCR) for locating visual anchor
  text in slide images.
- [FFmpeg](https://ffmpeg.org/) and
  [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) for media
  encoding and assembly.
- [PyTorch](https://github.com/pytorch/pytorch) and
  [FlashAttention](https://github.com/Dao-AILab/flash-attention) for accelerated
  local inference.
- [NumPy](https://github.com/numpy/numpy),
  [python-soundfile](https://github.com/bastibe/python-soundfile), and
  [Pillow](https://github.com/python-pillow/Pillow) for the dependable
  foundations used throughout the media pipeline.

OratorDeck is an independent project and is not endorsed by or affiliated with
these upstream projects. Each dependency and model retains its own license.

### License

OratorDeck is released under the [MIT License](LICENSE). The Voicebox patch
retains the upstream MIT notice; runtime libraries and model weights remain
under their own terms. See [Third-Party Notices](THIRD_PARTY_NOTICES.md).

---

<a id="简体中文"></a>

## 简体中文

### OratorDeck 是什么？

OratorDeck 通过生成带定时字幕和视觉锚点下划线标识的演讲视频，帮助用户快速准备 deck
演讲。视频以每张 slide 作为静态背景，并在讲到视觉锚点时标出对应元素。

它提供两种用法：

1. **Prompt-first skill：**用户准备每张 slide 的 prompt；skill 自动生成 slide 图片与
   同步讲稿，并继续完成整套视频流程。
2. **独立核心流水线：**用户自行准备讲稿和 slide 图片、保证二者一致，然后直接生成视频。

### 1. Prompt-first skill：从逐页 prompts 到最终视频

当 deck 仍处于创作阶段时，推荐使用这一方式。安装
[`oratordeck-prompt-first`](skills/oratordeck-prompt-first)，然后为每张 slide 准备一份
自包含的 Markdown prompt：

```text
resources/
├── slide-01_opening.md
├── slide-02_problem.md
├── slide-03_method.md
└── ...
```

每份文件都包含该 slide 的论证角色、观众应得出的结论以及 fenced 图片生成 prompt；所有
预期显示的文字都用双引号准确写出。完整模板见 skill 的
[prompt 约定](skills/oratordeck-prompt-first/references/prompt-contract.md)。

这些 prompts 是 deck 的权威源文件。在此基础上，skill 会：

1. 检查逐页论证、可见文字、阅读顺序和声明边界；
2. 为每份 prompt 生成一张匹配的 16:9 图片；
3. 从同一组 prompts 推导带预期时长的讲稿；
4. 把 slide 上的可见文字复用为讲稿中的加粗语音锚点；
5. 审计 prompts、图片、讲稿和锚点的覆盖关系；
6. 继续完成 TTS、字幕、OCR 匹配、逐页渲染和最终视频合成。

```text
逐页 Markdown prompts
          │
          ▼
 OratorDeck prompt-first skill
          │
          ├──> 相互一致的 slide 图片
          └──> 定时讲稿＋语音锚点
                       │
                       ▼
            OratorDeck 媒体流水线
                       │
                       ▼
       带朗读、字幕和锚点标识的最终 MP4
```

也就是说，当逐页 prompts 准备好后，skill 可以在一次引导式工作流中直接产出最终视频。
如果用户手中只有演讲需求或大纲，skill 也可以先帮助设计这些 prompts。

可以让 Codex 直接从以下地址安装：

```text
https://github.com/yuminhhuang/OratorDeck/tree/main/skills/oratordeck-prompt-first
```

也可以手工复制到 Codex skills 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/oratordeck-prompt-first "${CODEX_HOME:-$HOME/.codex}/skills/"
```

安装后可这样调用：

```text
Use $oratordeck-prompt-first with my per-slide prompts to generate the slide
images, synchronized English speaker notes, and final annotated video.
```

自动生成 slide 图片要求 agent 具备图片生成能力；媒体制作使用下文介绍的本地
OratorDeck 运行环境。skill 不会擅自发明缺失的证据、指标、引用或其他事实内容。

### 2. 独立核心流水线：使用自己的讲稿和图片

不安装 skill 也能独立使用 OratorDeck。用户只需准备：

- `resources/SPEAKER_NOTES.md`：每张 slide 的讲稿、预期时长和加粗视觉锚点；
- `resources/generated-images/`：每张有讲稿的 slide 对应一张渲染图片。

在这一模式下，**用户自行负责保证讲稿与图片表达相同内容**。OratorDeck 会在媒体生成
过程中保持这种对应关系，但不会自动推断或修复两份输入之间的语义不一致。

#### 讲稿约定

讲稿按每张幻灯片一个 section 编写：

```markdown
## Slide 01 - Opening

**Target time:** 0:45

Welcome to the presentation. We will begin with the **central question** and
then build the evidence step by step.
```

对应图片可以命名为 `slide-01.png`、`slide-01-opening.jpg` 或
`slide-01_opening.webp`。每张有讲稿的幻灯片必须恰好对应一张图片。

当前约定刻意保持简单：

1. 讲稿与图片中的 slide 编号连续且一致。
2. 每张 slide 恰好包含一个 `**Target time:** M:SS` 字段。
3. 加粗短语会被正常朗读，同时作为标注锚点。
4. 如果希望某个锚点被下划线标出，它也应当以清晰文字出现在对应图片中。
5. 两份输入在语义上是否一致，目前由用户负责保证。

预期时长是目标而非绝对保证。最终时长还会受到自然语音、模型表现和允许误差的影响。

#### 安装并运行核心流水线

使用 Python 3.11 安装 OratorDeck 依赖，并准备固定版本的 Voicebox 后端：

```bash
python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

scripts/setup-voicebox.sh
# 按输出提示安装 Voicebox 后端，然后运行：
ORATORDECK_TTS_GPU=0 scripts/run-voicebox.sh
```

包括 Qwen CustomVoice profile 创建在内的完整步骤见
[安装指南](docs/installation.md)。

复制讲稿模板、加入匹配的幻灯片图片，再编辑并运行刻意保持透明的工作流脚本：

```bash
cp resources/SPEAKER_NOTES.example.md resources/SPEAKER_NOTES.md
scripts/generate-keynote-workflow.sh
```

用户可以直接修改其中的输入路径、声音 profile、batch size、时间误差、GPU 和输出名称。

### 媒体流水线做什么

- 把一张 slide 始终保留为写作、TTS、时间控制、诊断和渲染的**不可再分单元**。
- 对完整 slide chunks 进行 GPU batch，不拆分单页讲稿。
- 输出逐页 WAV、完整演讲 WAV 和机器可读的时间报告。
- 使用 Whisper 时间戳制作字幕，并可依据原讲稿校正措辞。
- 把讲稿中的**加粗短语**作为视觉锚点。
- 通过 OCR 定位图片中的锚点文字，并在读到它时显示下划线。
- 为每张静态 slide 渲染视频片段，最后合并成完整 MP4。

```text
SPEAKER_NOTES.md ──> 逐页 chunks ──> 批量 TTS ──> 逐页 WAV
       │                                      │
       │                                      └──> 时间报告
       │
       └──> 加粗锚点

完整 WAV ──> Whisper 时间戳 ──> 原讲稿校正字幕

幻灯片图片 ──> OCR 坐标 ─────┐
加粗锚点 ────────────────────┼──> 定时下划线 ──> 逐页视频 ──> MP4
时间报告/字幕 ───────────────┘
```

### 运行输出

每次运行都会保存在一个带时间戳的集中目录中：

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
│   ├── my-talk.raw.srt
│   ├── my-talk.srt
│   ├── my-talk.vtt
│   └── my-talk.lrc
├── video/
│   ├── slides/
│   ├── annotation-report.json
│   └── my-talk.mp4
└── workflow.log
```

生成的媒体、模型权重、缓存、打过补丁的 Voicebox checkout、本地环境、日志和私有演示
材料都不会进入源码版本控制。

### 当前范围与限制

- 当前生产路径面向英文演讲。
- 为获得实用的 TTS 和转录速度，建议使用支持 CUDA 的 NVIDIA GPU。
- 背景是静态幻灯片图片；定时下划线是当前的视觉标注方式。
- OCR 只能定位图片中清晰可见的文字。
- 字幕时间可以提高锚点同步精度；缺少字幕时可按讲稿中的相对位置估算时间。
- 当前版本不会验证讲稿和图片是否陈述了相同事实。
- 模型权重单独下载，并分别受其自身许可证和条款约束。

### 路线图

- [x] 发布经过清理且可复现的源码。
- [ ] 增加项目级配置格式，同时保留容易直接编辑的工作流脚本。
- [x] 把 prompt-first 工作流封装为可选、可安装的 agent skill。
- [x] 接收描述演示内容的结构化 LLM prompts。
- [x] 从同一 prompt 表示同时生成相互匹配的幻灯片图片和讲稿。
- [ ] 在合成前自动检查视觉内容与讲稿的一致性。
- [ ] 支持可插拔的图片、TTS、转录和 OCR 后端。
- [ ] 支持逐页断点续作与更丰富的标注样式。

### 负责任地使用

只使用你拥有或已获授权的声音与材料。公开最终视频前，请人工检查生成的讲稿、字幕与
视觉标注。OratorDeck 的目标是辅助创作，而不是隐藏合成媒体的来源或在未经许可的情况下
冒充他人。

### 致谢

OratorDeck 得以实现，离不开优秀的开源生态。特别感谢：

- [Voicebox](https://github.com/jamiepine/voicebox) 的创建者 Jamie Pine
  及所有贡献者；当前 TTS 工作流建立在其本地语音工作室和推理 API 之上。
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) 及 Qwen 团队提供当前
  朗读路径所使用的语音模型。
- [OpenAI Whisper](https://github.com/openai/whisper) 与
  [Hugging Face Transformers](https://github.com/huggingface/transformers)
  提供语音识别与模型工具。
- [RapidOCR](https://github.com/RapidAI/RapidOCR) 用于在幻灯片图片中定位锚点文字。
- [FFmpeg](https://ffmpeg.org/) 与
  [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) 用于媒体编码与合成。
- [PyTorch](https://github.com/pytorch/pytorch) 与
  [FlashAttention](https://github.com/Dao-AILab/flash-attention) 提供本地加速推理基础。
- [NumPy](https://github.com/numpy/numpy)、
  [python-soundfile](https://github.com/bastibe/python-soundfile) 和
  [Pillow](https://github.com/python-pillow/Pillow) 提供可靠的媒体处理基础能力。

OratorDeck 是独立项目，不代表上述上游项目，也未获得其官方背书。每项依赖与模型仍受
各自许可证约束。

### 许可证

OratorDeck 使用 [MIT License](LICENSE) 发布。Voicebox 补丁保留上游 MIT 声明；
运行依赖和模型权重仍受其各自条款约束。详见
[第三方声明](THIRD_PARTY_NOTICES.md)。
