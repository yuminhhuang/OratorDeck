# OratorDeck Technical Architecture

[English](#english) · [简体中文](#简体中文)

This document describes the implementation, data contracts, intermediate
artifacts, validation strategy, and extension points. For user instructions,
start with the main [README](../README.md).

<a id="english"></a>

## English

### System boundaries

OratorDeck has three file-composable modules:

1. The optional OratorDeck skill implements the Prompt-as-Slide (PasS)
   protocol: one authoritative, self-contained Markdown prompt defines one
   slide and derives its aligned image and speaker notes.
2. The installable OratorDeck Verdict package uses CPU OCR and a self-contained
   browser editor to review aligned images, notes, anchors, timing goals, and
   normalized rectangles.
3. The standalone media pipeline turns original or reviewed images and notes
   into audio, subtitles, annotated slide clips, and a final MP4.

The media runtime does not consume prompt files, and the Verdict package
depends on neither the Agent layer nor the GPU media layer. SHA-bound files are
the only handoff between modules.

```text
slide-NN_slug.md PasS sources
          │
          ├──> prompt manifest ──> image generation ──> slide images ──────┐
          │
          └──> synchronized note generation ─────────> SPEAKER_NOTES.md ──┤
                                                                          ▼
                                          source inputs
                               ┌─────────────────┴─────────────────┐
                               ▼                                   ▼
                  optional concurrent pre-TTS             slide-atomic formatting
                         Deck Verdict                    and anchor extraction
                  (saved for the next run)                         │
                                                                          ▼
                              ┌───────────────────────────────────────────┴──────────────┐
                              ▼                                                          ▼
                      batched slide TTS                                           bold anchor data
                              │                                                          │
                              ├──> per-slide WAVs ──> joined WAV                         │
                              │                         │                                 │
                              │                         ▼                                 │
                              │                  Whisper subtitles                        │
                              │                         │                                 │
                              └──────── timing report ──┼─────────────────────────────────┤
                                                        ▼                                 ▼
                                       subtitle timing + OCR positions
                                               │
                              ┌────────────────┴─────────────────┐
                              ▼                                  ▼
             animation cues + post-TTS Verdict phase    annotated slide clips
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
- The default workflow never waits for human review. It snapshots any
  source-bound review that exists at launch and otherwise uses the source
  inputs directly.
- Inputs are copied into a timestamped run directory before generation.
- Long-running TTS and video reports are written progressively. Rendering runs
  end in `completed` or `failed`; video-planning dry runs end in `planned`.
- SHA-256 links derived artifacts to their exact source files.
- Generated media, models, caches, and private presentation inputs are ignored
  by Git.

### Stage 0: Prompt-as-Slide authoring

The installable skill is located at
`skills/oratordeck/`.

Under the Prompt-as-Slide (PasS) protocol, each `slide-NN_slug.md` source is
the authoritative definition of exactly one slide. It contains:

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

### Stage 1: pre-TTS Deck Verdict

The separately installable `oratordeck_verdict` package parses the notes,
discovers the slide images, runs RapidOCR on CPU, and performs global per-slide
anchor assignment. OCR parsing, text matching, candidate construction, and
global assignment have one canonical implementation in
`oratordeck_verdict/anchoring.py`; the video planner imports that module rather
than maintaining a second implementation.

The repository workflow treats `resources/` as read-only and writes a
self-contained `data/workspaces/<run_name>/verdict/deck-verdict.html` plus an
image-bound `deck-ocr.json` in the same persistent output workspace. The
standalone `oratordeck-verdict prepare` command accepts explicit output paths.
Slide previews and all editor data are embedded in the HTML. Editing uses
`oratordeck-verdict edit deck-verdict.html deck-review.json`, a loopback
service with no additional dependencies, implemented in
`oratordeck_verdict/state_server.py`. This is necessary because a `file://`
page cannot safely overwrite one fixed local JSON file.

The canonical shared editor in `oratordeck_verdict/editor.py` presents one
slide at a time with a filmstrip and previous/next navigation. Repository
scripts retain thin compatibility entry points. Slide pixels are read-only.
The visual editing surface is deliberately limited to one normalized
rectangular bounding box per anchor:

- dragging inside the rectangle moves it as a unit;
- four edge handles resize its top, right, bottom, or left boundary;
- unresolved anchors can receive a new box;
- an automatic box can be restored;
- an underline can be explicitly suppressed.

The inspector can edit the slide title, target time, and manuscript. Bold
Markdown spans remain the anchor definition, so adding, removing, or rewriting
`**anchor text**` updates the ordered anchor list. Diagnostics preserve the OCR
score, anchor-word coverage, candidate count, review reasons, and—after
subtitles exist—timing provenance.

The bound state file uses `oratordeck.deck-review.v1`, containing:

- the exact speaker-note SHA-256 and the SHA-256 of every slide image;
- the ordered slide identity, title, target time, and reviewed manuscript;
- the ordered anchor identity and text;
- one normalized box and `auto`, `manual`, `suppress`, or `unresolved` state per
  anchor.

The editor deliberately exposes only explicit **Save deck review** and
**Reset** actions. It has no import, browser autosave, or download-based state.
On page load and refresh, the panel reads its one bound JSON. Save atomically
overwrites that path; Reset atomically overwrites it with the generated initial
document embedded in the HTML. Unsaved in-memory edits disappear on refresh.

The state service listens only on `127.0.0.1`, exposes the page and state API
under a random per-process capability path, disables HTTP caching, and
validates the state format plus complete source fingerprint before reading or
writing. Opening the HTML directly is read-only, so the UI cannot silently
fall back to downloading a second, disconnected JSON.

The `edit` command can additionally receive a future `--post-html` and its
`--post-state`. In that form the service presents one workbench shell
containing two long-lived, same-origin editor frames. Only the pre-TTS frame is
loaded or visible initially. The server polls for the post artifact and accepts
it only after it is a complete `anchor-overrides` editor whose full slide-image
fingerprint equals the pre-TTS deck. Once accepted, the workbench loads the
post frame, reveals the phase selector, and switches automatically. The pre
frame remains alive, preserving unsaved in-memory edits across the automatic
switch. Returning from post to pre requires confirmation because semantic
changes invalidate more downstream artifacts.

The separate OCR intermediate uses format `oratordeck.ocr-results.v1` and
contains:

- the OCR engine and the minimum score retained while creating the artifact;
- one record per slide with image dimensions and exact image SHA-256;
- raw OCR text, confidence, and axis-aligned pixel box for every retained line.

It deliberately does not store final anchor assignments. The Verdict editor
may change the manuscript and its bold anchors, so the video stage filters the
cached lines at its requested confidence threshold and reruns the shared global
assignment against the final reviewed chunks. This reuses OCR inference without
freezing stale semantic decisions. The consumer validates the complete slide
set, dimensions, and hashes; any changed image is a hard error and requires the
pre stage to be regenerated.

`oratordeck-verdict apply` rejects a review when either source changed,
rebuilds Markdown, parses it through the package formatter, and verifies that
the derived anchor IDs and text exactly equal the review. It atomically emits
the reviewed `SPEAKER_NOTES.md`, `SPEAKER_NOTES_CHUNKS.json`,
`SPEAKER_NOTES_TTS.txt`, and source-bound `anchor-overrides.json`. When
`--ocr-results` is supplied, it also validates and copies `deck-ocr.json` into
the handoff directory. This prevents manuscript, TTS text, anchor offsets,
manually reviewed geometry, and image-bound OCR evidence from drifting apart.

The workflow prepares the verdict and OCR intermediate, launches the editor
server in the background by default, and immediately proceeds to media
generation. Its review decision is frozen at process launch. An existing
review is copied into the timestamped run, validated, and applied; without one,
the run formats the source notes directly. A review saved concurrently is
therefore never consumed halfway through a run. The user may ignore the panel,
or review while GPU stages run and interrupt/restart when a correction should
replace the current output. `open_pre_tts_verdict=false` disables automatic
browser launch without disabling artifact preparation or the printed editor
command.

### Stage 2: slide-atomic formatting

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

### Stage 3: batched TTS and duration control

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

### Stage 4: subtitle generation and reference correction

`scripts/generate-english-subtitles.py` loads a local Whisper model, transcribes
the joined WAV in bounded windows, and writes SRT, WebVTT, and LRC.

When a reference manuscript is provided, OratorDeck aligns Whisper tokens
against `SPEAKER_NOTES_TTS.txt`. If alignment is strong enough, standard
subtitle files use reference wording while preserving Whisper timing, and
`.raw` files retain the original transcription. If alignment is weak, the raw
Whisper wording becomes the standard output and the log requests manual review
of technical names.

Model downloads are redirected into the OratorDeck checkout.

### Stage 5: OCR anchor planning

`scripts/generate-keynote-video.py` verifies:

- the chunk document format and anchor offsets;
- the timing report format;
- the timing report's chunk SHA-256;
- one non-empty WAV per timing entry;
- one image per narrated slide;
- agreement between declared and measured WAV duration.

The planner imports the shared OCR and anchoring implementation from
`oratordeck_verdict/anchoring.py`. With `--ocr-results`, it verifies every
current image against the cached SHA-256 and dimensions, loads the raw OCR
lines, applies the requested confidence threshold, and does not import or
instantiate RapidOCR. Without that option it runs RapidOCR live through the
same module. The report records the OCR source plus the intermediate's path and
SHA-256 when reused.

Instead of committing each bold anchor to its best local match independently,
the shared planner keeps up to eight spatially distinct candidates per anchor.
A candidate's assignment quality combines fuzzy-text confidence (70%) and
exact anchor-word coverage (30%).

A bounded beam search then selects all anchors on a slide jointly. Candidate
utility includes a small reading-order prior. Assignments that reuse at least
half of another anchor's OCR tokens are incompatible unless one anchor's word
sequence contains the other or the two anchors are identical. Identical anchors
may reuse a location with a small penalty so distinct occurrences are preferred
when available. This preserves intentional nested anchors while preventing
unrelated anchors from silently claiming the same visual text. Matches selected
away from their local first choice and candidates rejected by a global conflict
remain explicit in the report.

Successful assignments are converted into anchor text boxes and separate
underline boxes; unsuccessful assignments remain unresolved.

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
- intentionally suppressed anchors use `status: suppressed`; applied manual
  geometry and its selection provenance remain attached as `manual_override`.

`anchor-verdict.html` is the post-TTS phase payload consumed by the same
restricted Deck Verdict workbench after audio and subtitle generation. It
embeds every slide, overlays numbered selected locations, and assigns every
anchor one of four verdicts:

- `pass`: the assignment cleared all configured checks;
- `corrected`: an accepted manual replacement or suppression is active;
- `review`: the assignment has low OCR confidence, low anchor-word coverage,
  spatially ambiguous candidates, a global reassignment, proportional timing,
  unexpected anchor-box overlap, or out-of-bounds source geometry;
- `unresolved`: no candidate passed or all candidates conflicted globally.

The inspector preserves OCR confidence, anchor coverage, candidate count,
timing provenance, and human-readable reasons. Default review thresholds are
0.78 confidence, 0.65 coverage, and 0.04 candidate-quality margin.

Before this payload exists, the workbench exposes no post-TTS control or frame.
The planner writes the payload atomically after the corrected-subtitle step and
before FFmpeg encoding. Its appearance is therefore the readiness signal that
causes an already open workbench to reveal the selector and move to post-TTS
automatically.

The post-TTS phase is deliberately box-only. The title, target time,
manuscript, and ordered anchor text are read-only because changing any of them
would invalidate the existing audio, subtitles, and timing map. The reviewer
may move, resize, create, restore, or suppress bounding boxes, then save
`oratordeck.anchor-overrides.v1` while reusing the existing audio/subtitles:

- `source.chunks_sha256` binds the corrections to the exact chunk document;
- `source.images[]` binds every processed slide number to its image SHA-256;
- each override targets a unique `(slide, anchor_id)` pair;
- `action: set` carries the normalized reviewed rectangle as one fragment;
- `action: suppress` deliberately renders no underline;
- optional `selection` metadata records the bounding-box editor as the source.

The post-TTS phase likewise exposes only **Save box overrides** and **Reset**.
It uses its own binding within the same state service: Save overwrites its fixed
`anchor-overrides.json`, Reset writes the generated initial override document,
and refresh reloads that file. The pre-TTS phase remains bound separately to
`deck-review.json`. Neither phase keeps browser-local or import state, so only
these two explicit JSON files can affect their respective rerun paths.

The renderer rejects stale sources, unknown or duplicate targets, non-finite
coordinates, zero-area boxes, and any fragment outside the 0–1 slide bounds.
Overrides are applied after global OCR assignment and before geometry verdicts,
cue generation, and FFmpeg rendering. A previous report therefore provides a
compact correction loop without repeating audio or subtitle work:

```bash
.venv/bin/python scripts/generate-keynote-video.py \
  --rerender-from-report RUN/video/anchor-video-report.json \
  --anchor-overrides RUN/video/anchor-overrides.json \
  --overwrite
```

Semantic changes must be made in the pre-TTS Deck Verdict and followed by a new
audio, subtitle, and video run.

The cue file, verdict, and audit report are written before FFmpeg starts.
`--dry-run` therefore performs the complete anchoring review without encoding
video.

### Stage 6: rendering and concatenation

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
- resolved, suppressed, and unresolved anchor counts;
- subtitle-timed and proportionally timed anchor counts;
- animation-cue and anchor-verdict artifact paths;
- override path/hash, applied action counts, and rerender source report;
- global matching method, reassignment/sharing counts, and verdict summary;
- per-slide OCR text, candidate diagnostics, verdict reasons, timing,
  text/underline boxes, and clip paths;
- `planned`, `rendering`, `completed`, or `failed` status.

### Timestamped workflow

`scripts/generate-keynote-workflow.sh` is intentionally a transparent
playground. Users edit its Verdict launch preference, voice profile, GPU, batch size,
tolerance, and run name directly.

Every invocation creates a timestamped run and continues through media
generation. It reads presentation inputs from `resources/` without writing
there. The persistent pre-TTS Verdict and OCR artifacts live in a run-name
workspace:

```text
data/workspaces/my-talk/verdict/
├── deck-verdict.html
├── deck-review.json
└── deck-ocr.json
```

The workflow prepares that workspace when needed and starts the unified
workbench server in the background, already pointing at the future
run-specific post artifact. If `deck-review.json` existed at launch, the
workflow snapshots, validates, and applies it; otherwise it uses the source
notes directly. Later pre-TTS saves are deferred to the next invocation. After
subtitle generation, publishing `anchor-verdict.html` activates and selects
the box-only phase in that same browser page. Standard output and standard
error are captured in `workflow.log`.

```text
data/runs/my-talk-YYYYMMDD-HHMMSS/
├── input/
│   ├── SPEAKER_NOTES.md
│   ├── SPEAKER_NOTES_CHUNKS.json
│   ├── SPEAKER_NOTES_TTS.txt
│   ├── deck-review.json          # only when present at launch
│   ├── deck-ocr.json
│   ├── anchor-overrides.json     # only when that review was applied
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
│   ├── anchor-verdict.html
│   ├── anchor-overrides.json    # state-bound box review
│   ├── anchor-video-report.json
│   └── my-talk.mp4
└── workflow.log
```

### Repository layout

```text
docs/                   user setup and technical architecture
data/                   Git-ignored workspaces, run snapshots, and generated outputs
examples/demo/          synthetic public smoke-test inputs
oratordeck_verdict/     installable Agent-free/GPU-free review package
patches/                pinned Voicebox batch API patch
resources/              read-only local presentation inputs
scripts/                formatter, TTS, subtitles, video, and workflow entrypoints
skills/                 installable OratorDeck authoring skill
tests/                  deterministic unit and contract tests
```

`vendor/`, `.venv/`, models, caches, private inputs, Verdict workspaces, and
generated runs are local-only.

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
- when a reviewed result is required, every slide is accepted in the pre-TTS
  Deck Verdict and that saved review is applied by a fresh run;
- every orange/red item in the unified workbench's post-TTS phase is reviewed;
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

OratorDeck 分为三个通过文件组合的模块：

1. 可选的 OratorDeck skill 实现 Prompt-as-Slide (PasS) 协议：一份权威、自包含的
   Markdown prompt 定义一张 slide，并派生其相互一致的图片和讲稿。
2. 可安装的 OratorDeck Verdict 包使用 CPU OCR 和自包含浏览器编辑器审查图片、讲稿、
   锚点、时间目标与归一化矩形框。
3. 独立媒体流水线把原始或已经审校的图片与讲稿转换为音频、字幕、带标注的逐页片段和
   最终 MP4。

媒体运行时不直接读取 prompt 文件；Verdict 包既不依赖 Agent 层，也不依赖 GPU 媒体
层。三个模块只通过带 SHA 绑定的普通文件交接。

```text
slide-NN_slug.md PasS 源
          │
          ├──> prompt manifest ──> 图片生成 ──> slide 图片 ──────┐
          │
          └──> 同步讲稿生成 ────────────────> SPEAKER_NOTES.md ──┤
                                                                 ▼
                                           源输入
                              ┌──────────────┴──────────────┐
                              ▼                             ▼
                    可选、并行的 TTS 前             逐页原子化格式与
                       Deck Verdict                    锚点提取
                   （保存供下一次 run 使用）                │
                                                                 ▼
                          ┌──────────────────────────────────────┴────────────┐
                          ▼                                                   ▼
                    逐页批量 TTS                                         加粗锚点数据
                          │                                                   │
                          ├──> 逐页 WAV ──> 完整 WAV                          │
                          │                   │                               │
                          │                   ▼                               │
                          │              Whisper 字幕                          │
                          │                   │                               │
                          └────── 时间报告 ───┼───────────────────────────────┤
                                              ▼                               ▼
                                  字幕时序＋OCR 坐标
                                        │
                         ┌──────────────┴───────────────┐
                         ▼                              ▼
              动画提示＋TTS 后 Verdict 阶段          带标注逐页片段
                                                        │
                                                        ▼
                                                     最终 MP4
```

### 设计不变量

- 一张 slide 是创作、语音合成、时间控制、诊断和渲染的最小单位。
- 单页讲稿不会为了 TTS 被拆成任意句子片段。
- GPU batch 只组合完整 slides，不改变 slide 边界。
- 默认工作流不会等待人工审阅；启动时已有的源绑定 review 会被快照，否则直接使用源输入。
- 开始生成前，输入会复制到带时间戳的运行目录。
- 长时间运行的 TTS 和视频报告会渐进写入。渲染运行最终标记为 `completed` 或
  `failed`，视频规划 dry run 标记为 `planned`。
- SHA-256 用于把派生产物绑定到确切源文件。
- 生成媒体、模型、缓存和私有演示输入均被 Git 忽略。

### 阶段 0：Prompt-as-Slide 创作

可安装 skill 位于 `skills/oratordeck/`。

在 Prompt-as-Slide (PasS) 协议中，每份 `slide-NN_slug.md` 都是一张 slide 的权威
定义，其中包含：

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

### 阶段 1：TTS 前 Deck Verdict

可单独安装的 `oratordeck_verdict` 包会解析讲稿、发现逐页图片、在 CPU 上运行
RapidOCR，并执行逐页全局锚点分配。OCR 解析、文字匹配、候选构造和全局分配只有一份
权威实现：`oratordeck_verdict/anchoring.py`。视频规划器直接导入该模块，不再维护第二套
实现。

仓库工作流把 `resources/` 视为只读输入，并把自包含的
`data/workspaces/<run_name>/verdict/deck-verdict.html` 与图片绑定的
`deck-ocr.json` 写入同一个持久输出工作区。独立的 `oratordeck-verdict prepare` 命令
接受显式输出路径。Slide 预览和全部编辑数据都嵌入 HTML。编辑时
使用 `oratordeck-verdict edit deck-verdict.html deck-review.json`；这是由
`oratordeck_verdict/state_server.py` 实现、不增加额外依赖的 loopback 服务。之所以需要
它，是因为 `file://` 页面无法安全覆写一个固定的本地 JSON 文件。

`oratordeck_verdict/editor.py` 是共用编辑器的权威实现：一次显示一页，并提供左侧
filmstrip 和前后翻页；仓库脚本保留轻量兼容入口。Slide 图片像素保持只读；视觉编辑被
刻意限制为每个锚点一个归一化矩形框：

- 拖动框内部可整体移动；
- 四个边缘 handle 分别调整上、右、下、左边界；
- unresolved 锚点可以新建框；
- 可以恢复自动 OCR 框；
- 可以明确 suppress 不需要的下划线。

Inspector 可以编辑 slide 标题、预期时间和讲稿。Markdown 加粗区域仍是锚点定义，因此
新增、删除或改写 `**anchor text**` 会同步更新有序锚点清单。诊断信息保留 OCR 分数、
锚点单词覆盖率、候选数量和 review 原因；字幕存在后还会显示时序来源。

绑定的状态文件使用 `oratordeck.deck-review.v1`，其中包含：

- 准确的讲稿 SHA-256 和每张 slide 图片的 SHA-256；
- 有序 slide identity、标题、预期时间和已审讲稿；
- 有序锚点 identity 和文字；
- 每个锚点的一个归一化框，以及 `auto`、`manual`、`suppress` 或 `unresolved` 状态。

编辑器刻意只提供显式的 **Save deck review** 与 **Reset**。它没有 import、浏览器
自动保存或下载式状态。页面打开和刷新时都会读取唯一绑定的 JSON；Save 原子化覆写该
路径，Reset 则用 HTML 内嵌的生成时初始文档原子化覆写它。未保存的内存修改会在刷新时
丢失。

状态服务只监听 `127.0.0.1`，把页面和状态 API 放在每次进程随机生成的 capability
路径下，关闭 HTTP 缓存，并在读写前校验状态格式和完整源指纹。直接打开 HTML 时页面
保持只读，因此不会静默退化成下载第二份、彼此脱节的 JSON。

`edit` 命令还可以接收未来的 `--post-html` 及其 `--post-state`。在这种模式下，服务只
提供一个 workbench 外壳，内部承载两个长期存活、同源的编辑 frame。初始只加载和显示
TTS 前 frame。服务持续检查 TTS 后产物，只有当它是完整的 `anchor-overrides` 编辑数据，
且全部 slide 图片指纹与 TTS 前 deck 一致时才接受。接受后，workbench 加载 TTS 后
frame、显示阶段切换器并自动切换；TTS 前 frame 仍保持存活，因此自动切换不会丢掉尚未
保存的内存修改。从 TTS 后返回 TTS 前必须确认，因为语义变化会使更多下游产物失效。

独立 OCR 中间产物的格式为 `oratordeck.ocr-results.v1`，包含：

- OCR 引擎，以及创建产物时保留的最低分数；
- 每张 slide 的图片尺寸和准确 SHA-256；
- 每条被保留 OCR 文字行的原文、置信度和轴对齐像素框。

它刻意不保存最终锚点分配。Verdict 编辑器可能修改讲稿和其中的加粗锚点，因此视频阶段会
按自身要求的置信度过滤缓存文字行，再针对最终已审 chunks 重新运行共用的全局分配。这样
既复用 OCR 推理，也不会固化已经过期的语义决策。消费方会检查完整 slide 集合、尺寸和
哈希；任何图片变化都会触发硬错误，要求重新运行 pre 阶段。

`oratordeck-verdict apply` 会在任一源文件变化时拒绝 review，重建 Markdown，交给包内
formatter 解析，并确认派生的锚点 ID 与文字和 review 完全一致。随后它原子化输出
已审 `SPEAKER_NOTES.md`、`SPEAKER_NOTES_CHUNKS.json`、
`SPEAKER_NOTES_TTS.txt` 和与源文件绑定的 `anchor-overrides.json`。提供
`--ocr-results` 时，它还会校验并把 `deck-ocr.json` 复制进交接目录。这样可以避免讲稿、
TTS 文本、锚点 offset、人工矩形和图片绑定的 OCR 证据发生漂移。

工作流会准备 verdict 与 OCR 中间产物，默认在后台启动编辑服务，并立即继续媒体生成。
Review 决定在进程启动时冻结：已有 review 会复制进带时间戳的 run，经校验和应用后再
进入 TTS；没有 review 时则直接格式化源讲稿。并行审阅期间保存的 JSON 不会在运行中途
被读入。用户可以忽略面板，也可以利用 GPU steps 的等待时间审阅；发现必要修正时再
中断并重跑。`open_pre_tts_verdict=false` 只关闭自动浏览器启动，不会关闭产物准备或
命令提示。

### 阶段 2：逐页原子化格式

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

### 阶段 3：批量 TTS 与时长控制

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

### 阶段 4：字幕生成与参考校正

`scripts/generate-english-subtitles.py` 加载本地 Whisper 模型，在有界窗口内转录完整 WAV，
并输出 SRT、WebVTT 和 LRC。

提供参考讲稿时，OratorDeck 会把 Whisper tokens 与 `SPEAKER_NOTES_TTS.txt` 对齐。如果
对齐足够强，标准字幕会使用参考讲稿措辞并保留 Whisper 时序，`.raw` 文件保留原始转录；
如果对齐过弱，原始 Whisper 措辞直接成为标准输出，日志会提示人工检查技术名词。

模型下载会重定向到 OratorDeck checkout 内。

### 阶段 5：OCR 锚点规划

`scripts/generate-keynote-video.py` 会检查：

- chunk 文档格式与锚点字符偏移；
- 时间报告格式；
- 时间报告中的 chunk SHA-256；
- 每个时间项对应一份非空 WAV；
- 每张有讲稿的 slide 恰好对应一张图片；
- 声明时长与实测 WAV 时长一致。

规划器导入 `oratordeck_verdict/anchoring.py` 中共用的 OCR 与锚定实现。提供
`--ocr-results` 时，它会用缓存的 SHA-256 和尺寸逐张校验当前图片，读取原始 OCR 文字行，
再按所需置信度过滤，并且不会导入或实例化 RapidOCR；没有该参数时则通过同一模块实时运行
RapidOCR。报告会记录 OCR 来源；复用中间产物时还会记录它的路径和 SHA-256。

每个加粗锚点会模糊匹配到一个或多个 OCR 文字行。共用规划器不会让每个锚点独立采用局部
最高分，而是为每个锚点保留至多八个空间位置不同的候选。候选的分配质量由模糊文字置信度
（70%）和精确锚点单词覆盖率（30%）共同组成。

随后使用有界 beam search 联合选择整页锚点，并加入轻量 reading-order 先验。如果两个
候选复用了至少一半 OCR tokens，除非一个锚点的单词序列包含另一个，或两者文字完全
相同，否则不能同时选择。完全相同的锚点可以复用位置，但会受到轻微惩罚，以便在存在
多个实例时优先选择不同位置。这样既保留刻意设计的嵌套锚点，也避免无关锚点悄悄占用
同一段视觉文字。未采用局部第一候选的全局改派，以及因全局冲突被拒绝的候选，都会明确
记录在报告中。

成功分配会分别转换为锚点文字框和下划线框；失败项会保留为 unresolved。

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
- 主动关闭的锚点使用 `status: suppressed`；人工位置及其选择来源保存在
  `manual_override` 中。

`anchor-verdict.html` 是音频与字幕生成后，由同一个受限 Deck Verdict workbench 消费
的 TTS 后阶段数据。它嵌入每张 slide、叠加带编号的位置，并为每个锚点给出四种
verdict：

- `pass`：通过全部自动检查；
- `corrected`：已经接受人工替换位置或 suppress 决策；
- `review`：存在低 OCR 置信度、低锚点单词覆盖率、空间候选歧义、全局改派、
  比例时序、意外的锚点框重叠或源几何越界；
- `unresolved`：没有合格候选，或所有候选都发生全局冲突。

Inspector 保留 OCR 置信度、锚点覆盖率、候选数量、时序来源和可读原因。默认复核阈值
为 0.78 置信度、0.65 覆盖率和 0.04 候选质量分差。

该数据不存在时，workbench 不显示任何 TTS 后控件，也不加载 TTS 后 frame。校正字幕
步骤结束后，规划器会在 FFmpeg 编码前原子写出该数据；它的完整出现就是 readiness
信号，使已经打开的 workbench 显示切换器并自动进入 TTS 后阶段。

TTS 后阶段被严格限制为 box-only。标题、预期时间、讲稿和有序锚点文字均为只读，
因为任一变化都会使已有音频、字幕和时序映射失效。Reviewer 只能移动、缩放、新建、
恢复或 suppress bounding box，然后保存 `oratordeck.anchor-overrides.v1`，继续复用已有
音频和字幕：

- `source.chunks_sha256` 将修正绑定到准确的 chunks 文档；
- `source.images[]` 将每个页号绑定到对应图片的 SHA-256；
- 每条 override 唯一定位 `(slide, anchor_id)`；
- `action: set` 把已审归一化矩形作为一个 fragment；
- `action: suppress` 明确表示不渲染下划线；
- 可选的 `selection` 元数据记录修改来自 bounding-box editor。

TTS 后阶段同样只提供 **Save box overrides** 与 **Reset**，并在同一状态服务中使用
自己的绑定：Save 覆写固定的 `anchor-overrides.json`，Reset 写回生成时的初始 override
文档，刷新则重新读取该文件。TTS 前阶段仍单独绑定 `deck-review.json`。两个阶段都不
维护浏览器本地草稿或 import 状态，因此只有这两份显式 JSON 能分别影响各自的重跑路径。

渲染器会拒绝过期输入、未知或重复目标、非有限坐标、零面积框以及任何超出 0–1 边界的
fragment。Overrides 在全局 OCR 分配之后、几何 verdict、cues 和 FFmpeg 渲染之前应用。
因此可以从上一次报告直接完成修正闭环，无需重复音频与字幕阶段：

```bash
.venv/bin/python scripts/generate-keynote-video.py \
  --rerender-from-report RUN/video/anchor-video-report.json \
  --anchor-overrides RUN/video/anchor-overrides.json \
  --overwrite
```

语义变化必须在 TTS 前 Deck Verdict 中完成，然后重新生成音频、字幕和视频。

动画提示、verdict 和审计报告都会在 FFmpeg 启动前写出。因此 `--dry-run` 可以完成整套
锚定复核而不编码视频。

### 阶段 6：渲染与合并

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
- resolved、suppressed 与 unresolved 锚点数量；
- 字幕时序与比例回退时序的锚点数量；
- 动画提示和锚点 verdict 产物路径；
- override 路径/哈希、已应用 action 数量和重渲染来源报告；
- 全局匹配方法、改派/共享数量和 verdict 汇总；
- 每页 OCR 文字、候选诊断、verdict 原因、时序、文字/下划线坐标框和片段路径；
- `planned`、`rendering`、`completed` 或 `failed` 状态。

### 带时间戳的工作流

`scripts/generate-keynote-workflow.sh` 刻意保持为透明的 playground。用户直接编辑
Verdict 启动偏好、声音 profile、GPU、batch size、时间容差和运行名称。

每次调用都会创建带时间戳的 run 并继续媒体生成。工作流只读取 `resources/`，不会在
其中写入产物。持久的 TTS 前 Verdict 与 OCR 产物位于按运行名称区分的工作区：

```text
data/workspaces/my-talk/verdict/
├── deck-verdict.html
├── deck-review.json
└── deck-ocr.json
```

工作流会按需准备该工作区，并在后台启动统一 workbench 服务，同时预先指向本次 run
尚未生成的 TTS 后产物。如果启动时已有 `deck-review.json`，就会快照、校验并应用它；
否则直接使用源讲稿。之后 TTS 前 Save 的修改会留到下一次调用。字幕生成后，
`anchor-verdict.html` 的发布会在同一个浏览器页面中激活并选择 box-only 阶段。标准输出
与错误输出统一写入 `workflow.log`。

```text
data/runs/my-talk-YYYYMMDD-HHMMSS/
├── input/
│   ├── SPEAKER_NOTES.md
│   ├── SPEAKER_NOTES_CHUNKS.json
│   ├── SPEAKER_NOTES_TTS.txt
│   ├── deck-review.json          # 仅启动时已存在才有
│   ├── deck-ocr.json
│   ├── anchor-overrides.json     # 仅应用上述 review 后才有
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
│   ├── anchor-verdict.html
│   ├── anchor-overrides.json    # 状态绑定的 box review
│   ├── anchor-video-report.json
│   └── my-talk.mp4
└── workflow.log
```

### 仓库结构

```text
docs/                   用户安装与技术架构
data/                   Git 忽略的工作区、run 快照和生成输出
examples/demo/          公开合成 smoke-test 输入
oratordeck_verdict/     可安装、无需 Agent/GPU 的审校包
patches/                固定版本的 Voicebox batch API 补丁
resources/              只读的本地演示输入
scripts/                格式化、TTS、字幕、视频和工作流入口
skills/                 可安装的 OratorDeck 创作 skill
tests/                  确定性单元测试和契约测试
```

`vendor/`、`.venv/`、模型、缓存、私有输入、Verdict 工作区和生成结果只保留在本地。

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
- 当结果必须经过审校时，在 TTS 前 Deck Verdict 中逐页确认，并通过一次新的 run 应用
  已保存 review；
- 人工复核统一 workbench 的 TTS 后阶段中所有橙色/红色项目；
- 人工检查时间误差和 unresolved anchors；
- `workflow.log` 中没有 traceback 或显存不足错误。

### 扩展点与路线图

- 增加项目级配置 schema，同时保持工作流脚本可直接编辑。
- 增加确定性的视觉内容与讲稿一致性检查。
- 支持可插拔的图片、TTS、转录和 OCR 后端。
- 支持逐页断点续作。
- 支持更丰富的视觉标注样式。

新后端应保留 slide 原子性、稳定 ID、源文件哈希、渐进报告和显式质量失败。
