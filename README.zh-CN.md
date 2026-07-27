# OratorDeck

> 生成带视觉锚点下划线的演讲视频，并提供匹配的独立定时字幕文件，帮助你更快准备
> 幻灯片演示。

![OratorDeck 最终效果：演讲视频在读到视觉锚点时添加下划线，并提供独立的定时字幕文件](docs/assets/oratordeck-final-effect.png)

[English](README.md) · [简体中文](README.zh-CN.md)

## OratorDeck 能做什么？

OratorDeck 把 slide 图片和英文讲稿转换为完整的演讲视频。每张 slide 会在对应讲稿播放
期间保持显示；当读到图片中可见的锚点短语时，视频会为它添加下划线。匹配的字幕以独立
SRT、WebVTT 和 LRC 文件提供。

结果可以用于演练、审阅、分享或发布演示，无需手工录制和剪辑每张 slide。

每次运行还会生成锚点位置文件，帮助用户在原始可编辑 presentation 中制作对应的
出现/退出动画。

可选的 **Deck Verdict** 面板可以逐页查看演示、编辑讲稿和加粗锚点，并直接在图片上
修正锚点框。一键工作流不会等待审阅：你可以忽略面板，也可以在 GPU steps 运行期间
检查；只有发现值得修正的问题时才需要中断并重跑。它最初只显示 TTS 前完整审校；
带字幕时序的锚点规划准备好后，同一个面板会自动切换到 TTS 后 box 修正，并显示两个
阶段的切换控件。

![Deck Verdict：逐页审阅演示、编辑锚点框，并通过颜色快速发现问题](docs/assets/oratordeck-verdict-panel.png)

OratorDeck 分为三个可以独立使用、也可以组合的模块：

1. **Skill 辅助创作：**可选的 [`oratordeck`](skills/oratordeck) skill 使用
   **Prompt-as-Slide (PasS) 协议**——以一份权威、自包含的 Markdown prompt 定义一张
   slide——创建相互对齐的 slide 图片和同步讲稿。
2. **独立审校：**可单独安装的 `oratordeck-verdict` 面板可以在没有 Agent 或 GPU 的
   环境中审查图片、讲稿、锚点、预期时间和锚点框。
3. **媒体生成：**仓库工作流把准备好的图片和讲稿转换为音频、字幕、锚点 cues 和最终
   标注视频。

```text
PasS prompts → 图片＋讲稿 ───────────────→ 演讲视频
 可选 Agent       │                        GPU 媒体环境
                  └→ 可选 Deck Verdict
                        仅 CPU/浏览器
```

## OratorDeck 适合你吗？

可以根据主要目标快速选择：

| 你的主要目标 | 更合适的起点 |
| --- | --- |
| 使用相互对齐的 slide 图片和讲稿制作长篇英文演讲，并在读到可见短语时为其添加下划线 | **OratorDeck** |
| 现在用 Prompt-as-Slide 创建 slide 图片和同步讲稿，稍后或换一台设备再生成媒体 | 可选的 **OratorDeck skill** |
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

## 方式一：使用 Prompt-as-Slide (PasS)

PasS 使用一份自包含 Markdown prompt 作为一张 slide 的权威定义，其中包含该页的目的、
准确可见文字、构图和证据边界；slide 图片与同步讲稿都从这个共同源派生。

为每张 slide 创建一份 PasS 源文件：

```text
resources/
├── slide-01_opening.md
├── slide-02_problem.md
├── slide-03_method.md
└── ...
```

如果手中只有大纲，skill 可以帮助你把它改写成一组论证连贯、顺序明确的 PasS 源文件。

从以下地址安装 [`oratordeck`](skills/oratordeck) skill：

```text
https://github.com/yuminhhuang/OratorDeck/tree/main/skills/oratordeck
```

然后告诉 Codex：

```text
Use $oratordeck to apply the Prompt-as-Slide (PasS) protocol to my presentation
and generate aligned slide images with synchronized English speaker notes.
```

skill 会停在图片和讲稿准备、审查完成之后，不会安装或运行本地媒体环境。事实、数字、
引用及其他源材料仍由用户负责。

如果媒体环境和 GPU 已经准备好，可以补充：

```text
After the slide images and speaker notes pass their audit, continue outside the
skill by running scripts/generate-keynote-workflow.sh to produce the final
media.
```

## 方式二：使用自己的图片和讲稿

准备好以下内容后，既不要求 skill，也不要求 Agent：

```text
resources/
├── SPEAKER_NOTES.md
└── generated-images/
    ├── slide-01_opening.png
    ├── slide-02_problem.png
    └── ...
```

用户需要保证每张图片与对应讲稿表达相同内容。在 `SPEAKER_NOTES.md` 中为每张 slide
编写一个 section：

```markdown
## Slide 01 - Opening

**Target time:** 0:45

Welcome to the presentation. We will begin with the **central question** and
then build the evidence step by step.
```

加粗短语会被正常朗读。当相同短语清晰显示在对应图片中时，OratorDeck 会尝试在读到它时
添加下划线。

讲稿和图片中的 slide 编号必须连续且一致。图片可以命名为 `slide-01.png`、
`slide-01-opening.jpg` 或 `slide-01_opening.webp`。

## 安装本地媒体环境

如果只使用 skill 或独立 Deck Verdict，可以跳过本节。

```bash
git clone https://github.com/yuminhhuang/OratorDeck.git
cd OratorDeck

python3.11 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

scripts/setup-voicebox.sh
```

按照 `setup-voicebox.sh` 输出的命令安装 Voicebox backend，然后启动：

```bash
ORATORDECK_TTS_GPU=0 scripts/run-voicebox.sh
```

运行媒体工作流前，需要在 Voicebox 中创建英文 Qwen CustomVoice profile。完整配置和
故障排查见[安装指南](docs/installation.md)。

## 生成演讲视频

编辑 `scripts/generate-keynote-workflow.sh`，设置运行名称、Voicebox profile、GPU 和
需要的时间参数，然后运行：

```bash
scripts/generate-keynote-workflow.sh
```

这一条命令会在 `data/runs/` 下的时间戳目录中生成音频、字幕、锚点 cues 和最终视频。

生成继续进行的同时，可选 Deck Verdict 工作台会以 TTS 前模式在后台打开。你可以忽略
它，也可以利用等待 GPU steps 的时间审阅：

- 使用左侧缩略图、按钮或 Page Up/Page Down 翻页；
- 编辑 slide 标题、预期时间、讲稿和 `**加粗锚点**`；
- 移动或缩放锚点框；
- 新建、恢复或关闭锚点框；
- 点击 **Save deck review** 保存修改；
- 点击 **Reset** 恢复面板初始状态。

校正字幕时序与最终锚点规划准备好之前，TTS 后阶段不会显示；准备完成后，工作台会自动
切换过去。此阶段会锁定讲稿与锚点文字，但允许根据真实时序诊断修正 box。随后可以在
两个阶段之间切换；从 TTS 后切回 TTS 前时，面板会提示语义修改需要重跑音频、字幕、
锚点规划和视频。

TTS 前 Save 不会改变已经运行中的任务；如果修改有必要，应 Save、中断当前任务并重新
运行。TTS 后 Save 的 box 修正则可以直接用于重渲染现有 run，无需重复 TTS 或字幕。
工作流结束时会在醒目的 **Deck Verdict — Next Steps After Save** 区块中再次给出两条
准确命令，避免它们淹没在生成日志里。

需要重新打开面板时，请使用工作流输出的编辑器命令。直接打开 HTML 时面板只读。如果
不希望自动打开浏览器，可以在工作流脚本中设置
`open_pre_tts_verdict=false`。

## 只安装 Deck Verdict

如果只想审查准备好的图片和讲稿，而不安装 skill、TTS、FFmpeg 或 GPU 环境，可以使用：

```bash
python3.11 -m venv .verdict-venv
.verdict-venv/bin/python -m pip install \
  "oratordeck-verdict @ git+https://github.com/yuminhhuang/OratorDeck.git"
```

准备、打开并应用 review：

```bash
oratordeck-verdict prepare SPEAKER_NOTES.md generated-images \
  --output deck-verdict.html \
  --review-json deck-review.json \
  --ocr-output deck-ocr.json

oratordeck-verdict edit deck-verdict.html deck-review.json

oratordeck-verdict apply \
  deck-review.json SPEAKER_NOTES.md generated-images \
  --ocr-results deck-ocr.json \
  --output-dir reviewed
```

打开面板期间需保持 `edit` 命令运行。**Save deck review** 会更新
`deck-review.json`；**Reset** 会恢复面板初始状态。随后可以把 `reviewed/` 目录交给
其他系统，或继续用于 OratorDeck 媒体工作流。

## 结果与修正

多数用户主要需要以下文件：

```text
data/runs/my-talk-YYYYMMDD-HHMMSS/
├── audio/my-talk.wav
├── subtitles/my-talk.srt
├── subtitles/my-talk.vtt
├── subtitles/my-talk.lrc
├── video/my-talk.mp4
├── video/anchor-animation-cues.json
├── video/anchor-verdict.html
└── workflow.log
```

主要交付物是 `video/my-talk.mp4`。工作流也会在同一 run 目录中保留逐页媒体与诊断文件。

`video/anchor-verdict.html` 是同一个 Deck Verdict 工作台的 TTS 后阶段数据。此阶段
会锁定讲稿和锚点，但仍可移动、缩放、新建、恢复或关闭下划线框。该文件完整生成之前，
这个阶段保持隐藏；生成后，已经打开的工作台会自动选择它。

使用以下命令在一个工作台中重新打开两个阶段：

```bash
.venv/bin/python -m oratordeck_verdict edit \
  resources/.oratordeck/deck-verdict.html \
  resources/.oratordeck/deck-review.json \
  --post-html data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-verdict.html \
  --post-state data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-overrides.json
```

保存 box 修正后，无需重复 TTS 或字幕生成即可重渲染已有 run：

```bash
.venv/bin/python scripts/generate-keynote-video.py \
  --rerender-from-report data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-video-report.json \
  --anchor-overrides data/runs/my-talk-YYYYMMDD-HHMMSS/video/anchor-overrides.json \
  --overwrite
```

如果需要修改讲稿、预期时间或加粗锚点，应把工作台切回 TTS 前阶段，Save 后开始新的
媒体 run。

## 当前限制

- 当前本地媒体工作流面向英文演讲。
- Slide 背景是静态图片。
- 字幕以独立文件提供，不会烧录进 MP4。
- 锚点文字必须在图片中清晰可见，才能准确添加下划线。
- Deck Verdict 不能修改 slide 图片的像素和布局。
- 预期时长是目标值；实际语速可能快于或慢于要求。
- 发布前应人工检查生成的 slide、讲稿、字幕和锚点。

## 更多文档

- [安装与环境配置](docs/installation.md)
- [技术架构、数据契约和仓库内部实现](docs/architecture.md#简体中文)
- [第三方声明](THIRD_PARTY_NOTICES.md)

## 负责任地使用

只使用你拥有或已获授权的声音与材料。OratorDeck 用于辅助创作，不应用于冒充他人或隐藏
合成媒体的来源。

## 致谢

OratorDeck 建立在
[Voicebox](https://github.com/jamiepine/voicebox)、
[Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)、
[OpenAI Whisper](https://github.com/openai/whisper)、
[Hugging Face Transformers](https://github.com/huggingface/transformers)、
[RapidOCR](https://github.com/RapidAI/RapidOCR)、
[FFmpeg](https://ffmpeg.org/)、
[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)、
[PyTorch](https://github.com/pytorch/pytorch)、
[FlashAttention](https://github.com/Dao-AILab/flash-attention)、
[NumPy](https://github.com/numpy/numpy)、
[python-soundfile](https://github.com/bastibe/python-soundfile) 和
[Pillow](https://github.com/python-pillow/Pillow) 的工作之上。感谢这些项目的维护者与
贡献者。

OratorDeck 是独立项目，不代表上述上游项目，也未获得其官方背书。

## 许可证

OratorDeck 使用 [MIT License](LICENSE) 发布。运行依赖和模型权重仍受各自许可证与条款
约束。
