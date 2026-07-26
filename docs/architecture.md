# OratorDeck Technical Architecture

[English](#english) · [简体中文](#简体中文)

This document describes the implementation, data contracts, intermediate
artifacts, validation strategy, and extension points. For user instructions,
start with the main [README](../README.md).

<a id="english"></a>

## English

### System boundaries

OratorDeck has two layers:

1. The optional OratorDeck skill turns authoritative per-slide Markdown
   prompts into aligned slide images and speaker notes.
2. The standalone media pipeline turns aligned images and notes into audio,
   subtitles, annotated slide clips, and a final MP4.

The core runtime does not consume prompt files. Skill-assisted authoring is a
source-generation layer that produces the core runtime's two inputs.

```text
slide-NN_slug.md prompts
          │
          ├──> prompt manifest ──> image generation ──> slide images
          │
          └──> synchronized note generation ─────────> SPEAKER_NOTES.md
                                                       │
                                                       ▼
                              slide-atomic formatting and anchor extraction
                                                       │
                     ┌─────────────────────────────────┴──────────────┐
                     ▼                                                ▼
             batched slide TTS                                bold anchor data
                     │                                                │
                     ├──> per-slide WAVs ──> joined WAV               │
                     │                         │                       │
                     │                         ▼                       │
                     │                  Whisper subtitles              │
                     │                         │                       │
                     └──────── timing report ──┼───────────────────────┤
                                               ▼                       ▼
                                       subtitle timing + OCR positions
                                               │
                              ┌────────────────┴─────────────────┐
                              ▼                                  ▼
                    normalized animation cues       annotated slide clips
                                                                  │
                                                                  ▼
                                                              final MP4
```

### Design invariants

- A slide is the smallest unit of authorship, synthesis, timing, diagnosis, and
  rendering.
- Narration for one slide is never split into arbitrary sentence fragments for
  TTS.
- GPU batching groups complete slides without changing slide boundaries.
- Inputs are copied into a timestamped run directory before generation.
- Long-running TTS and video reports are written progressively. Rendering runs
  end in `completed` or `failed`; video-planning dry runs end in `planned`.
- SHA-256 links derived artifacts to their exact source files.
- Generated media, models, caches, and private presentation inputs are ignored
  by Git.

### Stage 0: skill-assisted authoring

The installable skill is located at
`skills/oratordeck/`.

Each `slide-NN_slug.md` source contains:

- a presentation or defense role;
- an audience takeaway;
- one fenced image-generation prompt;
- exact visible strings in double quotes;
- composition, reading order, and claim-discipline rules.

The prompt layer provides two deterministic tools:

- `build_prompt_manifest.py` extracts prompts in slide order and records the
  target PNG path, visible-text manifest, and source SHA-256.
- `audit_slide_assets.py` checks prompt numbering and structure, optional
  image coverage and aspect ratios, speaker-note timing, anchor correspondence,
  anchor gaps, and expected speaking pace.

Image generation itself is delegated to an image-capable agent. Speaker notes
are derived from the same prompts so that bold spoken anchors reuse visible
slide wording. The resulting images and `SPEAKER_NOTES.md` then enter the core
pipeline.

### Stage 1: slide-atomic formatting

`scripts/format-speaker-notes-chunks.py` parses
`resources/SPEAKER_NOTES.md`.

For each `## Slide NN - Title` section, it:

1. requires exactly one `**Target time:** M:SS` line;
2. removes non-spoken Markdown while preserving readable text;
3. removes bold markers but records every bold phrase as an anchor;
4. stores each anchor's exact character offsets in the cleaned text;
5. calculates characters, words, target seconds, and target WPM;
6. rejects empty slides, invalid timing, non-contiguous numbering, and
   indivisible text longer than 5,000 characters.

It writes `SPEAKER_NOTES_CHUNKS.json` with format identifier
`oratordeck.speaker-notes-chunks.v1`. The document contains:

- source filename and SHA-256;
- chunk count and total target duration;
- ordered slide chunks;
- cleaned narration text;
- target timing and WPM;
- anchor identifiers, text, and character offsets.

An optional `SPEAKER_NOTES_TTS.txt` is a plain-text rendering of the cleaned
narration and serves as the subtitle correction reference.

### Stage 2: batched TTS and duration control

`scripts/generate-english-keynote.py` reads the chunk document and verifies its
format, counts, timing totals, and source hash.

The current production engine is Qwen CustomVoice 1.7B through the patched
Voicebox service. The patch adds `POST /generate/atomic-batch`, which accepts
several complete slide chunks and returns one WAV per chunk.

For each slide, OratorDeck:

1. converts target words and target seconds into an instructed WPM;
2. submits complete slides in GPU batches;
3. measures each returned WAV;
4. accepts it when it falls inside the timing tolerance;
5. otherwise adjusts instructed WPM from the measured duration and retries;
6. retains the attempt closest to the target;
7. joins the selected slide WAVs without changing their internal content.

The default workflow uses a batch size of four, two timing attempts, and an
eight-percent tolerance. Batch size is bounded at eight.

The timing report uses format
`oratordeck.keynote-timing-report.v1`. It records:

- chunk input and SHA-256;
- Voicebox profile, engine, model size, and batch settings;
- every timing attempt and instructed WPM;
- selected attempt, actual duration, and relative error per slide;
- per-slide WAV paths;
- target and selected total durations;
- progress plus final `completed` or `failed` status.

Target duration is best-effort. The report exposes misses rather than hiding or
time-stretching them.

### Stage 3: subtitle generation and reference correction

`scripts/generate-english-subtitles.py` loads a local Whisper model, transcribes
the joined WAV in bounded windows, and writes SRT, WebVTT, and LRC.

When a reference manuscript is provided, OratorDeck aligns Whisper tokens
against `SPEAKER_NOTES_TTS.txt`. If alignment is strong enough, standard
subtitle files use reference wording while preserving Whisper timing, and
`.raw` files retain the original transcription. If alignment is weak, the raw
Whisper wording becomes the standard output and the log requests manual review
of technical names.

Model downloads are redirected into the OratorDeck checkout.

### Stage 4: OCR anchor planning

`scripts/generate-keynote-video.py` verifies:

- the chunk document format and anchor offsets;
- the timing report format;
- the timing report's chunk SHA-256;
- one non-empty WAV per timing entry;
- one image per narrated slide;
- agreement between declared and measured WAV duration.

RapidOCR extracts visible text lines and bounding boxes from each slide image.
Each bold anchor is fuzzy-matched to one or more OCR lines. Successful matches
are converted into anchor text boxes and separate underline boxes; unsuccessful
matches are retained as unresolved anchors.

Anchor timing uses two strategies:

1. Match the anchor's spoken words against subtitle word timing.
2. Fall back to the anchor's proportional character position in the slide
   narration.

The fallback ensures rendering can continue when subtitle alignment is
incomplete, while the report preserves the timing source and match score.

The same planning pass writes `anchor-animation-cues.json` using format
`oratordeck.anchor-animation-cues.v1`. Its contract is:

- slides retain their 1-based presentation number;
- every slide records its source image dimensions and SHA-256;
- anchors retain their 1-based narration order within the slide as
  `appearance_order`;
- `position` is the union bounding box around the matched anchor text;
- `fragments` preserves individual boxes when an anchor spans multiple lines;
- every box uses normalized `x`, `y`, `width`, `height`, `center_x`, and
  `center_y` values in the inclusive 0–1 coordinate space;
- the coordinate origin is the source slide image's top-left corner, with x
  increasing rightward and y increasing downward;
- unresolved anchors remain in order with `position: null` and no fragments.

The cue file and audit report are written before FFmpeg starts. `--dry-run`
therefore performs OCR planning and produces both JSON artifacts without
encoding video.

### Stage 5: rendering and concatenation

Each slide is rendered as a static-background H.264/AAC clip with:

- its selected per-slide WAV;
- time-bounded underline overlays;
- an even-sized YUV420 video frame suitable for broad playback.

The clips are concatenated in slide order into the final MP4. FFmpeg is supplied
through `imageio-ffmpeg`.

`anchor-video-report.json` uses format
`oratordeck.anchor-video-report.v1` and records:

- chunk, timing, image, subtitle, and output paths;
- chunk SHA-256;
- frame rate and underline settings;
- total duration and slide count;
- resolved and unresolved anchor counts;
- subtitle-timed and proportionally timed anchor counts;
- the animation-cue artifact path;
- per-slide OCR text, anchor scores, timing, text/underline boxes, and clip
  paths;
- `planned`, `rendering`, `completed`, or `failed` status.

### Timestamped workflow

`scripts/generate-keynote-workflow.sh` is intentionally a transparent
playground. Users edit its voice profile, GPU, batch size, tolerance, and run
name directly.

Before generation it snapshots the current notes and images. Standard output
and standard error are captured in `workflow.log`.

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
│   ├── my-talk.raw.srt       # these .raw files are present when reference
│   ├── my-talk.raw.vtt       # correction is applied
│   ├── my-talk.raw.lrc
│   ├── my-talk.srt
│   ├── my-talk.vtt
│   └── my-talk.lrc
├── video/
│   ├── clips/
│   ├── anchor-animation-cues.json
│   ├── anchor-video-report.json
│   └── my-talk.mp4
└── workflow.log
```

### Repository layout

```text
docs/                   user setup and technical architecture
examples/demo/          synthetic public smoke-test inputs
patches/                pinned Voicebox batch API patch
resources/              local presentation inputs
scripts/                formatter, TTS, subtitles, video, and workflow entrypoints
skills/                 installable OratorDeck authoring skill
tests/                  deterministic unit and contract tests
```

`vendor/`, `.venv/`, models, caches, private inputs, and generated runs are
local-only.

### Validation and tests

Run deterministic tests and lint:

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m ruff check .
```

Validate the skill package:

```bash
python /path/to/skill-creator/scripts/quick_validate.py \
  skills/oratordeck
```

Run the public source smoke test:

```bash
./.venv/bin/python scripts/create-demo-slides.py
./.venv/bin/python scripts/format-speaker-notes-chunks.py \
  examples/demo/SPEAKER_NOTES.md \
  --output examples/demo/SPEAKER_NOTES_CHUNKS.json \
  --tts-output examples/demo/SPEAKER_NOTES_TTS.txt
./.venv/bin/python scripts/generate-english-keynote.py \
  examples/demo/SPEAKER_NOTES_CHUNKS.json \
  --dry-run
```

Production validation should additionally confirm:

- all reports end in `completed`;
- prompt, image, note, WAV, and clip counts agree;
- final WAV, subtitle end, report duration, and MP4 duration agree;
- the final MP4 has H.264 video and AAC audio;
- cue and report slide/anchor counts agree;
- timing misses and unresolved anchors are reviewed;
- `workflow.log` contains no traceback or out-of-memory failure.

### Extension points and roadmap

- Add a project-level configuration schema while keeping the workflow script
  directly editable.
- Add deterministic visual-versus-narrative consistency checks.
- Support pluggable image, TTS, transcription, and OCR backends.
- Add resumable per-slide generation.
- Support richer visual annotation styles.

New backends should preserve slide atomicity, stable identifiers, source
hashing, progressive reports, and explicit quality failures.

---

<a id="简体中文"></a>

## 简体中文

### 系统边界

OratorDeck 分为两层：

1. 可选的 OratorDeck skill 把权威的逐页 Markdown prompts 转换为相互一致的 slide
   图片和讲稿。
2. 独立媒体流水线把已经对齐的图片与讲稿转换为音频、字幕、带标注的逐页片段和最终
   MP4。

核心运行时不直接读取 prompt 文件。Skill 辅助创作层负责生成核心运行时所需的两份
输入。

```text
slide-NN_slug.md prompts
          │
          ├──> prompt manifest ──> 图片生成 ──> slide 图片
          │
          └──> 同步讲稿生成 ────────────────> SPEAKER_NOTES.md
                                                   │
                                                   ▼
                                    逐页原子化格式与锚点提取
                                                   │
                    ┌──────────────────────────────┴──────────────┐
                    ▼                                             ▼
              逐页批量 TTS                                  加粗锚点数据
                    │                                             │
                    ├──> 逐页 WAV ──> 完整 WAV                    │
                    │                   │                         │
                    │                   ▼                         │
                    │              Whisper 字幕                    │
                    │                   │                         │
                    └────── 时间报告 ───┼─────────────────────────┤
                                        ▼                         ▼
                                  字幕时序＋OCR 坐标
                                        │
                         ┌──────────────┴───────────────┐
                         ▼                              ▼
                    归一化动画提示                 带标注逐页片段
                                                        │
                                                        ▼
                                                     最终 MP4
```

### 设计不变量

- 一张 slide 是创作、语音合成、时间控制、诊断和渲染的最小单位。
- 单页讲稿不会为了 TTS 被拆成任意句子片段。
- GPU batch 只组合完整 slides，不改变 slide 边界。
- 开始生成前，输入会复制到带时间戳的运行目录。
- 长时间运行的 TTS 和视频报告会渐进写入。渲染运行最终标记为 `completed` 或
  `failed`，视频规划 dry run 标记为 `planned`。
- SHA-256 用于把派生产物绑定到确切源文件。
- 生成媒体、模型、缓存和私有演示输入均被 Git 忽略。

### 阶段 0：Skill 辅助创作

可安装 skill 位于 `skills/oratordeck/`。

每份 `slide-NN_slug.md` 包含：

- 该页的演示或答辩角色；
- 观众应得到的结论；
- 一份 fenced 图片生成 prompt；
- 用双引号明确写出的可见文字；
- 构图、阅读顺序和声明边界规则。

Prompt 层提供两个确定性工具：

- `build_prompt_manifest.py` 按 slide 顺序提取 prompts，记录目标 PNG 路径、可见文字清单
  和源文件 SHA-256。
- `audit_slide_assets.py` 检查 prompt 编号与结构、可选的图片覆盖和宽高比、讲稿时间、
  锚点对应关系、锚点间隔与预期语速。

图片生成本身交给具有图片生成能力的 agent。讲稿从同一组 prompts 推导，使加粗语音锚点
复用 slide 中的可见文字。生成的图片和 `SPEAKER_NOTES.md` 随后进入核心流水线。

### 阶段 1：逐页原子化格式

`scripts/format-speaker-notes-chunks.py` 解析
`resources/SPEAKER_NOTES.md`。

对于每个 `## Slide NN - Title` section，它会：

1. 要求恰好一个 `**Target time:** M:SS` 字段；
2. 删除不参与朗读的 Markdown，同时保留可读文字；
3. 删除加粗标记，但把每个加粗短语记录成锚点；
4. 在清理后的文本中保存每个锚点的精确字符偏移；
5. 计算字符数、词数、预期秒数和预期 WPM；
6. 拒绝空白讲稿、错误时间、不连续编号以及超过 5,000 字符的不可拆分文本。

它输出格式标识为 `oratordeck.speaker-notes-chunks.v1` 的
`SPEAKER_NOTES_CHUNKS.json`，其中包含：

- 源文件名和 SHA-256；
- chunk 数量与总预期时长；
- 有序 slide chunks；
- 清理后的讲稿；
- 时间目标和 WPM；
- 锚点 ID、文字和字符偏移。

可选的 `SPEAKER_NOTES_TTS.txt` 是清理后讲稿的纯文本版本，也作为字幕校对参考。

### 阶段 2：批量 TTS 与时长控制

`scripts/generate-english-keynote.py` 读取 chunk 文档，并检查格式、数量、总时长和源文件
哈希。

当前生产引擎通过打过补丁的 Voicebox 服务使用 Qwen CustomVoice 1.7B。补丁新增
`POST /generate/atomic-batch`，可一次接收多个完整 slide chunks，并为每项返回一份 WAV。

对每张 slide，OratorDeck 会：

1. 根据目标词数和目标秒数计算指示 WPM；
2. 以 GPU batch 提交完整 slides；
3. 测量返回的 WAV；
4. 如果落在时间误差内就接受；
5. 否则根据实测时长调整 WPM 并重试；
6. 保留最接近目标的尝试；
7. 合并选中的逐页 WAV，不改变每页内部内容。

默认工作流使用 batch size 4、两次时长尝试和 8% 容差；batch size 上限为 8。

时间报告格式为 `oratordeck.keynote-timing-report.v1`，记录：

- chunk 输入及 SHA-256；
- Voicebox profile、引擎、模型大小和 batch 设置；
- 每次时长尝试及指示 WPM；
- 每页选中尝试、实际时长和相对误差；
- 逐页 WAV 路径；
- 目标总时长与选中总时长；
- 进度以及最终 `completed` 或 `failed` 状态。

目标时长是尽力满足的目标。报告会暴露未命中情况，而不是隐藏误差或强行变速。

### 阶段 3：字幕生成与参考校正

`scripts/generate-english-subtitles.py` 加载本地 Whisper 模型，在有界窗口内转录完整 WAV，
并输出 SRT、WebVTT 和 LRC。

提供参考讲稿时，OratorDeck 会把 Whisper tokens 与 `SPEAKER_NOTES_TTS.txt` 对齐。如果
对齐足够强，标准字幕会使用参考讲稿措辞并保留 Whisper 时序，`.raw` 文件保留原始转录；
如果对齐过弱，原始 Whisper 措辞直接成为标准输出，日志会提示人工检查技术名词。

模型下载会重定向到 OratorDeck checkout 内。

### 阶段 4：OCR 锚点规划

`scripts/generate-keynote-video.py` 会检查：

- chunk 文档格式与锚点字符偏移；
- 时间报告格式；
- 时间报告中的 chunk SHA-256；
- 每个时间项对应一份非空 WAV；
- 每张有讲稿的 slide 恰好对应一张图片；
- 声明时长与实测 WAV 时长一致。

RapidOCR 从每张 slide 图片提取可见文字行和坐标框。每个加粗锚点会模糊匹配到一个或多个
OCR 文字行。匹配成功后会分别转换为锚点文字框和下划线框；匹配失败的锚点会作为
unresolved anchors 保留下来。

锚点时序有两种来源：

1. 把锚点语音文字与字幕单词时序匹配。
2. 如果匹配失败，则使用锚点字符位置在该页讲稿中的相对比例。

回退策略让字幕对齐不完整时仍可继续渲染，同时在报告中保留时序来源和匹配分数。

同一次规划还会写出格式为 `oratordeck.anchor-animation-cues.v1` 的
`anchor-animation-cues.json`。其数据契约为：

- 每张 slide 保留从 1 开始的演示页号；
- 每张 slide 记录源图片尺寸与 SHA-256；
- 每个锚点通过 `appearance_order` 保留其在该页讲稿中从 1 开始的出现次序；
- `position` 是匹配到的锚点文字整体包围框；
- 锚点跨越多行时，`fragments` 保留各行的独立包围框；
- 每个框都使用 0–1 闭区间内的归一化 `x`、`y`、`width`、`height`、`center_x`
  和 `center_y`；
- 坐标原点是源 slide 图片左上角，x 向右增大，y 向下增大；
- 未定位锚点仍按原次序保留，`position` 为 `null`，且没有 fragments。

动画提示文件和审计报告会在 FFmpeg 启动前写出。因此 `--dry-run` 可以只执行 OCR 规划
并生成这两份 JSON，而不编码视频。

### 阶段 5：渲染与合并

每张 slide 会被渲染为静态背景的 H.264/AAC 片段，并包含：

- 该页选中的 WAV；
- 有明确起止时间的下划线覆盖层；
- 适合广泛播放的偶数尺寸 YUV420 视频帧。

所有片段按 slide 顺序合并为最终 MP4。FFmpeg 由 `imageio-ffmpeg` 提供。

`anchor-video-report.json` 的格式为
`oratordeck.anchor-video-report.v1`，记录：

- chunk、时间报告、图片、字幕和输出路径；
- chunk SHA-256；
- 帧率与下划线设置；
- 总时长与 slide 数量；
- resolved 与 unresolved 锚点数量；
- 字幕时序与比例回退时序的锚点数量；
- 动画提示产物路径；
- 每页 OCR 文字、锚点分数、时序、文字/下划线坐标框和片段路径；
- `planned`、`rendering`、`completed` 或 `failed` 状态。

### 带时间戳的工作流

`scripts/generate-keynote-workflow.sh` 刻意保持为透明的 playground。用户直接编辑声音
profile、GPU、batch size、时间容差和运行名称。

开始生成前，它会复制当前讲稿和图片。标准输出与错误输出统一写入 `workflow.log`。

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
│   ├── my-talk.raw.srt       # 应用参考校正时存在这些 .raw 文件
│   ├── my-talk.raw.vtt
│   ├── my-talk.raw.lrc
│   ├── my-talk.srt
│   ├── my-talk.vtt
│   └── my-talk.lrc
├── video/
│   ├── clips/
│   ├── anchor-animation-cues.json
│   ├── anchor-video-report.json
│   └── my-talk.mp4
└── workflow.log
```

### 仓库结构

```text
docs/                   用户安装与技术架构
examples/demo/          公开合成 smoke-test 输入
patches/                固定版本的 Voicebox batch API 补丁
resources/              本地演示输入
scripts/                格式化、TTS、字幕、视频和工作流入口
skills/                 可安装的 OratorDeck 创作 skill
tests/                  确定性单元测试和契约测试
```

`vendor/`、`.venv/`、模型、缓存、私有输入和生成结果只保留在本地。

### 验证与测试

运行确定性测试和 lint：

```bash
./.venv/bin/python -m pytest -q
./.venv/bin/python -m ruff check .
```

验证 skill 包：

```bash
python /path/to/skill-creator/scripts/quick_validate.py \
  skills/oratordeck
```

运行公开源文件 smoke test：

```bash
./.venv/bin/python scripts/create-demo-slides.py
./.venv/bin/python scripts/format-speaker-notes-chunks.py \
  examples/demo/SPEAKER_NOTES.md \
  --output examples/demo/SPEAKER_NOTES_CHUNKS.json \
  --tts-output examples/demo/SPEAKER_NOTES_TTS.txt
./.venv/bin/python scripts/generate-english-keynote.py \
  examples/demo/SPEAKER_NOTES_CHUNKS.json \
  --dry-run
```

生产验证还应确认：

- 所有报告最终状态为 `completed`；
- prompt、图片、讲稿、WAV 和片段数量一致；
- 最终 WAV、字幕结束时间、报告时长和 MP4 时长一致；
- 最终 MP4 包含 H.264 视频与 AAC 音频；
- 动画提示和视频报告中的 slide/anchor 数量一致；
- 人工检查时间误差和 unresolved anchors；
- `workflow.log` 中没有 traceback 或显存不足错误。

### 扩展点与路线图

- 增加项目级配置 schema，同时保持工作流脚本可直接编辑。
- 增加确定性的视觉内容与讲稿一致性检查。
- 支持可插拔的图片、TTS、转录和 OCR 后端。
- 支持逐页断点续作。
- 支持更丰富的视觉标注样式。

新后端应保留 slide 原子性、稳定 ID、源文件哈希、渐进报告和显式质量失败。
