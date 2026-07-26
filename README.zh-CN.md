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

每次媒体生成还会输出一份机器可读的锚点映射，包含页号、锚点在该页中从 1 开始的出现
次序，以及归一化位置。用户可以用它把锚点匹配到原始可编辑 slide 中的元素，并为这些
元素制作出现/退出动画。

在创作与媒体生成之间，自包含的 **Deck Verdict** 会以受限 slide 编辑器的形式打开整个
演示。用户可以逐页翻阅、检查 OCR 选中的锚点、编辑讲稿及其中的加粗锚点，并通过移动
矩形或拉动上、右、下、左四条边来修正每个锚点的 bounding box；slide 图片本身保持
只读。这个 review gate 会在成本更高的音视频生成前集中发现问题。

OratorDeck 刻意拆分为三个可以独立使用、也可以组合的模块：

1. **Skill 辅助创作：**可选的 `$oratordeck` skill 把逐页 prompts 转换为相互对齐的
   slide 图片和同步讲稿，不要求本地媒体环境或本地 GPU。
2. **独立质量审校：**可单独安装的 `oratordeck-verdict` 包把图片和讲稿转换为浏览器
   review gate，并应用保存的审校决定；不要求 Agent 或 GPU。
3. **独立媒体生成：**仓库工作流把已审图片和讲稿转换为音频、字幕和标注视频。输入
   准备好后，这一部分不要求 skill 或 Agent。

模块之间只通过普通文件交接，因此可以单独使用任意模块，也可以依次串联：

```text
逐页 prompts → 图片＋讲稿 → Deck Verdict → 演讲视频
 可选 Agent       仅 CPU/浏览器        GPU 媒体环境
```

## OratorDeck 适合你吗？

可以根据主要目标快速选择：

| 你的主要目标 | 更合适的起点 |
| --- | --- |
| 使用相互对齐的 slide 图片和讲稿制作长篇英文演讲，并在读到可见短语时为其添加下划线 | **OratorDeck** |
| 现在用 prompts 创建 slide 图片和同步讲稿，稍后或换一台设备再生成媒体 | 可选的 **OratorDeck skill** |
| 不使用 Agent 或 GPU，审查图片与讲稿的一致性、加粗锚点、时间目标及锚点框 | 独立的 **OratorDeck Verdict** 包 |
| 通过 GUI 或 Agent 制作并手工调整原生、可编辑的 PPTX | [Presenton](https://github.com/presenton/presenton) 或 [PPT Master](https://github.com/hugohe3/ppt-master) |
| 从研究论文 PDF 直接生成带烧录字幕和区域视觉提示的短篇研究视频 | [ResearchStudio Paper2Video](https://github.com/microsoft/ResearchStudio/tree/main/ResearchStudio-Reel/skills/paper2video) |
| 只需自动生成 presentation deck，不需要配音或标注视频 | [Presenton](https://github.com/presenton/presenton)、[PPT Master](https://github.com/hugohe3/ppt-master) 或 [PPTAgent](https://github.com/icip-cas/PPTAgent) |

OratorDeck 是专注于演讲视频的命令行工作流，不是通用 PowerPoint 编辑器，也不是一键式
论文摘要工具。当你重视长篇讲稿、逐页时间、独立字幕文件和精确文字锚点的控制时，它会
比较合适。完整的本地媒体工作流目前面向 Python 3.11 和 NVIDIA CUDA GPU；它不会生成
可编辑 PPTX，字幕也以独立文件提供，而不是烧录进视频。

这些工具并不互斥。你可以在其他工具中制作 deck，再导出 slide 图片，并把讲稿整理为
OratorDeck 的输入格式。没有本地 GPU 的设备可以使用创作 skill 和/或 Deck Verdict；
没有 Agent 的 GPU 工作站则可以使用 Deck Verdict 与媒体生成。

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

这是手工输入路径。准备好以下两份输入后，既不要求安装 skill，也不要求使用 Agent：

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

## 在 TTS 前 review 整个演示

默认工作流第一次运行时会刻意停在音频生成之前，并创建两个自包含的 TTS 前产物：

```text
resources/.oratordeck/deck-verdict.html
resources/.oratordeck/deck-ocr.json
```

运行命令输出的状态绑定编辑器，并在打开面板期间保持该进程运行：

```bash
.venv/bin/python -m oratordeck_verdict edit \
  resources/.oratordeck/deck-verdict.html \
  resources/.oratordeck/deck-review.json
```

它会在浏览器中打开一个小型、受限的 presentation 编辑器：

- 用左侧缩略图、Previous/Next 或 Page Up/Page Down 翻页；
- 在右侧编辑本页标题、预期时长和讲稿；
- 通过修改 `**加粗短语**` 新增、删除或重写锚点；
- 选中锚点框后，拖动框内区域可整体移动矩形；
- 拉动上、右、下、左四个 handle，可单独调整对应边；
- 为未定位锚点新建框、恢复 OCR 框，或明确关闭不需要的下划线；
- 查看所选锚点的 OCR 分数、单词覆盖率、候选数量、时序来源和 review 原因。

面板总是绑定到 `edit` 命令指定的 JSON 路径；顶栏刻意只保留两个会改变状态的动作：

- **Save deck review**：原子化覆写绑定的
  `resources/.oratordeck/deck-review.json`；
- **Reset**：用 HTML 生成时的初始状态覆写同一个 JSON。

页面不维护浏览器自动保存或 import 状态。刷新时会重新载入绑定 JSON，因此已 Save 的
修改仍然存在，未 Save 的修改会被丢弃。直接以 `file://` 打开 HTML 时，页面会刻意保持
只读，因为普通网页不能安全覆写固定的本地文件。轻量编辑服务只监听 `127.0.0.1`，并
使用每次启动随机生成的 capability URL。

Review 文件与准确的讲稿及逐页图片哈希绑定。再次运行工作流时，OratorDeck 会先验证
review，再一次性生成相互一致的已审讲稿、chunks、TTS 参考文本和锚点 overrides，
之后才调用 TTS。`deck-ocr.json` 另外保存原始 OCR 文字行、置信度、坐标、图片尺寸及
每张图片的 SHA-256。视频阶段验证这些哈希并复用 OCR 文字行，但会针对最终已审讲稿
重新执行锚点分配。两阶段调用同一个 OCR/锚定模块，因此匹配行为不会逐渐分叉。

这个面板是质量 gate，不是像素级 slide 编辑器。如果 prompt 生成或导入的图片本身有误，
应重新生成或替换该图，然后重建 verdict 并再次 review；讲稿、时间、加粗锚点和
bounding box 则可以直接在面板中修正。

### 只安装 Deck Verdict

Deck Verdict 是带 CPU OCR 和自包含浏览器 UI 的轻量 Python 包。它不会安装 OratorDeck
skill、Voicebox、PyTorch、Whisper、FFmpeg 或任何 GPU runtime：

```bash
python3.11 -m venv .verdict-venv
.verdict-venv/bin/python -m pip install \
  "oratordeck-verdict @ git+https://github.com/yuminhhuang/OratorDeck.git"
```

使用任意一组相互匹配的讲稿与图片准备 review：

```bash
oratordeck-verdict prepare SPEAKER_NOTES.md generated-images \
  --output deck-verdict.html \
  --review-json deck-review.json \
  --ocr-output deck-ocr.json
```

用固定状态文件打开面板，逐页审校并点击 **Save deck review**：

```bash
oratordeck-verdict edit deck-verdict.html deck-review.json
```

完成后用 Ctrl+C 停止编辑服务，再验证并应用保存的决定：

```bash
oratordeck-verdict apply \
  deck-review.json SPEAKER_NOTES.md generated-images \
  --ocr-results deck-ocr.json \
  --output-dir reviewed
```

`reviewed/` 会集中包含一致的讲稿、逐页 chunks、字幕/TTS 参考文本、锚点 overrides
和可复用的 `deck-ocr.json`。你可以把它们交给其他系统；如果要继续 OratorDeck 媒体
工作流，则把 review 与 OCR 文件分别放到
`resources/.oratordeck/deck-review.json` 和
`resources/.oratordeck/deck-ocr.json`。详情见
[安装指南](docs/installation.md#install-only-deck-verdict)。

## 安装本地媒体环境

如果只使用 skill 或独立 Deck Verdict，可以跳过本节。要在本地生成音频和视频，建议
使用 Python 3.11 和支持 CUDA 的 NVIDIA GPU；准备 Voicebox 还需要 Git 和
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
然后先运行一次以准备 Deck Verdict：

```bash
scripts/generate-keynote-workflow.sh
```

运行输出的 `oratordeck_verdict edit` 命令。它会打开
`resources/.oratordeck/deck-verdict.html`，并将其绑定到
`resources/.oratordeck/deck-review.json`；完成 review 后点击 Save。用 Ctrl+C 停止
编辑服务，再次执行同一条工作流命令，才会生成音频、字幕、锚点 cues 和视频。只有明确
想绕过这一 gate 时，才应在 playground 脚本中把 `review_before_tts` 设为 `false`。

## 完整媒体工作流会生成什么？

每次运行都保存在一个带时间戳的目录中：

```text
data/runs/my-talk-YYYYMMDD-HHMMSS/
├── input/
│   ├── SPEAKER_NOTES.md
│   ├── SPEAKER_NOTES_CHUNKS.json
│   ├── SPEAKER_NOTES_TTS.txt
│   ├── deck-review.json
│   ├── deck-ocr.json
│   ├── anchor-overrides.json
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
│   ├── anchor-animation-cues.json
│   ├── anchor-verdict.html
│   ├── anchor-overrides.json    # 人工修正后生成
│   ├── anchor-video-report.json
│   └── my-talk.mp4
└── workflow.log
```

主要结果是 `video/my-talk.mp4`。此外还会得到完整音频、独立字幕文件、逐页音频和视频、
输入快照、时间信息、锚点结果以及完整生成日志。
复制到 `input/deck-ocr.json` 的中间产物避免视频规划器再次对未变化图片运行 RapidOCR；
图片哈希不匹配会直接报错，而不会静默退化为错误缓存。
`video/anchor-animation-cues.json` 是供可编辑 slide 动画使用的精简中间产物：成功定位
的锚点包含归一化的 `x`/`y`/`width`/`height` 包围框与中心点；未定位锚点仍按原次序
保留，并将位置设为 `null`，因此后续动画编号不会错位。
媒体阶段会把 `video/anchor-verdict.html` 写成同一编辑器的 TTS 后 box-only 版本，并
额外加入字幕时序诊断。讲稿、预期时间和锚点文字均为只读，因为修改它们会使已有音频与
字幕失效；这里只允许移动、缩放、新建、恢复或 suppress bounding box。

用它拥有的 JSON 打开 TTS 后面板：

```bash
.venv/bin/python -m oratordeck_verdict edit \
  data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-verdict.html \
  data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-overrides.json
```

顶栏同样只保留 **Save box overrides** 和 **Reset**。Save 覆写绑定的
`video/anchor-overrides.json`；Reset 用面板的初始 box 状态覆写它，刷新则重新载入它。
保存后只重渲染当前 run，无需重新执行 TTS 和字幕生成：

```bash
.venv/bin/python scripts/generate-keynote-video.py \
  --rerender-from-report data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-video-report.json \
  --anchor-overrides data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-overrides.json \
  --overwrite
```

Overrides 文件与准确的 chunks 内容及逐页图片 SHA-256 绑定；过期修正会在 FFmpeg
启动前被拒绝。重渲染后的 verdict 会把已接受的人工决策标记为 `corrected`。如需修改
讲稿、预期时间或加粗锚点，应回到 TTS 前 Deck Verdict，并重新生成音频、字幕和视频。

## 当前限制

- 当前独立媒体工作流面向英文演讲。
- Slide 背景是静态图片；下划线锚点用于提供视觉强调。
- 定时字幕以独立的 SRT、WebVTT 和 LRC 文件提供，当前不会烧录或封装进 MP4。
- 只有当锚点文字在图片中清晰可见时，才能准确添加下划线。
- Deck Verdict 可以编辑讲稿、锚点、时间和 bounding box，但不能修改 slide 图片的
  像素与布局。
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
