# OratorDeck

> Turn coherent slides and speaker notes into a narrated, captioned, visually
> annotated presentation video — locally.

[English](#english) · [简体中文](#简体中文)

<a id="english"></a>

## English

### What is OratorDeck?

OratorDeck is a local-first production pipeline for turning a slide deck into a
polished presentation video.

Today, it accepts two aligned inputs:

- `resources/SPEAKER_NOTES.md` — the narration, target duration, and visual
  anchors for each slide.
- `resources/generated-images/` — one rendered image for each slide.

The user currently guarantees that the notes and slide images describe the same
content. OratorDeck preserves that alignment through slide-atomic text-to-speech,
reference-corrected subtitles, OCR-based visual matching, and deterministic
video assembly.

An optional agent skill now adds a prompt-first authoring layer: it helps define
the desired slides as self-contained Markdown prompts, generates images and
synchronized narration from those shared sources, audits their contract, and
then passes the aligned assets through the existing video pipeline. The core
runtime remains usable without the skill. The name **OratorDeck** is
intentionally not tied to one model or one renderer.

### What works today

- Parses Markdown notes into **one indivisible chunk per slide**.
- Reads a target duration for every slide and asks the TTS engine for a matching
  speaking pace.
- Batches complete slide chunks for GPU throughput without splitting a slide's
  narration.
- Produces one WAV per slide plus a joined keynote WAV and a machine-readable
  timing report.
- Transcribes the generated speech with Whisper and can correct its wording
  against the source manuscript while retaining the detected timestamps.
- Treats **bold phrases** in the notes as visual anchors.
- Finds those anchors in the slide image with OCR and underlines them when the
  corresponding words are spoken.
- Renders one static-background video clip per slide and concatenates the clips
  into a final MP4.
- Keeps the inputs, intermediate artifacts, reports, logs, and final output for
  each run in one timestamped directory.
- Ships an optional installable skill for prompt-defined slides, aligned image
  and speaker-note generation, source auditing, and pipeline handoff.

### Pipeline

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

Each slide remains the unit of authorship, synthesis, timing, diagnosis, and
rendering. A failure on one slide can therefore be inspected or regenerated
without turning the presentation into arbitrary sentence fragments.

### Input contract

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

### Quick start

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
selection, and output name directly in that file. A run produces a layout
similar to:

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

### Optional prompt-first skill

The installable skill lives at
[`skills/oratordeck-prompt-first`](skills/oratordeck-prompt-first). It can:

1. turn a presentation brief into one authoritative Markdown prompt per slide;
2. use an available image-generation capability to render one matching image
   per prompt;
3. derive timed speaker notes whose bold anchors reuse visible slide wording;
4. audit prompt, note, and image coverage before running OratorDeck;
5. configure, monitor, and verify the existing end-to-end media workflow.

Ask Codex to install it directly from:

```text
https://github.com/yuminhhuang/OratorDeck/tree/main/skills/oratordeck-prompt-first
```

Or copy the skill directory into your Codex skills directory:

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/oratordeck-prompt-first "${CODEX_HOME:-$HOME/.codex}/skills/"
```

Then invoke it explicitly, for example:

```text
Use $oratordeck-prompt-first to turn my 12-slide research talk brief into
prompt-defined slide images, synchronized English speaker notes, and a video.
```

Image rendering requires an image-generation capability available to the
agent. The skill keeps factual claims under user control and does not invent
missing evidence, metrics, or citations.

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

OratorDeck 是一套本地优先的演示视频生产流水线，用于把一组幻灯片制作成完整的演讲视频。

当前版本接收两份已经对齐的输入：

- `resources/SPEAKER_NOTES.md`：每张幻灯片的讲稿、预期时长和视觉锚点。
- `resources/generated-images/`：每张幻灯片对应的一张渲染图片。

现阶段由用户保证讲稿与图片表达的是同一内容。OratorDeck 通过以幻灯片为原子单位的
TTS、参考讲稿校正的字幕、基于 OCR 的视觉匹配以及确定性的视频合成，在后续流程中保持
这种对应关系。

现在还提供一个可选的 agent skill 作为 prompt-first 创作层：它帮助用户把目标幻灯片
定义成自包含的 Markdown prompts，再从同一来源生成图片与同步讲稿、审计输入约定，并把
对齐后的材料送入现有视频流水线。核心运行时不安装 skill 也可独立使用。
**OratorDeck** 这个名字刻意不绑定某个模型或某个渲染器。

### 当前已实现

- 把 Markdown 讲稿解析为**每张幻灯片一个不可再分的 chunk**。
- 读取每张幻灯片的预期时长，并据此向 TTS 模型要求相应语速。
- 对完整的 slide chunks 进行 GPU batch，在不拆分单页讲稿的前提下提高吞吐量。
- 输出逐页 WAV、合并后的完整 WAV 和机器可读的时间报告。
- 使用 Whisper 转录语音；在保留识别时间戳的同时，可用原讲稿校正术语和措辞。
- 把讲稿中的**加粗短语**作为视觉锚点。
- 通过 OCR 在幻灯片图片中定位锚点，并在读到相应内容时显示下划线。
- 为每张静态幻灯片生成视频片段，最后合并为完整 MP4。
- 把每次运行的输入、中间产物、报告、日志和最终结果集中到一个带时间戳的目录。
- 提供可选、可直接安装的 prompt-first skill，用于 prompts 定义、图片与讲稿协同生成、
  源文件审计及现有流水线交接。

### 流水线

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

一张幻灯片始终是写作、语音合成、时间控制、问题诊断和视频渲染的最小单位。因此，某一页
出现问题时可以单独检查或重新生成，不会把整场演讲切成缺乏语义的任意句子碎片。

### 输入约定

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

### 快速开始

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
每次运行会生成类似下面的集中目录：

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

### 可选的 prompt-first skill

可安装 skill 位于
[`skills/oratordeck-prompt-first`](skills/oratordeck-prompt-first)。它可以：

1. 把演示需求转换成每张 slide 一份权威 Markdown prompt；
2. 调用 agent 可用的图片生成能力，为每份 prompt 生成一张匹配图片；
3. 生成含预期时长和可见文字锚点的同步讲稿；
4. 在运行 OratorDeck 前审计 prompt、讲稿和图片的覆盖关系；
5. 配置、监控并验收现有端到端媒体工作流。

可以让 Codex 直接从以下地址安装：

```text
https://github.com/yuminhhuang/OratorDeck/tree/main/skills/oratordeck-prompt-first
```

也可以手工复制到 Codex skills 目录：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R skills/oratordeck-prompt-first "${CODEX_HOME:-$HOME/.codex}/skills/"
```

安装后可这样显式调用：

```text
Use $oratordeck-prompt-first to turn my 12-slide research talk brief into
prompt-defined slide images, synchronized English speaker notes, and a video.
```

自动渲染图片要求 agent 本身具备图片生成能力。skill 不会为了补齐页面而擅自发明证据、
指标或引用。

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
