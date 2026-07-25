# Third-Party Notices

OratorDeck depends on open-source software and separately downloaded model
weights. Dependencies are not relicensed by OratorDeck. Users and distributors
remain responsible for complying with each upstream license.

## Voicebox-derived patch

`patches/voicebox-qwen-batching.patch` modifies source files from
[jamiepine/voicebox](https://github.com/jamiepine/voicebox), based on commit
`52f8d8dd387e4049c81ee97079d5f54e2e399b94`.

Voicebox is distributed under the MIT License:

> MIT License
>
> Copyright (c) 2026 Voicebox Contributors
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
> OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
> SOFTWARE.

## Runtime dependencies

The following table is a convenience summary, not a substitute for the
upstream license text.

| Component | Role | Upstream license |
| --- | --- | --- |
| [Voicebox](https://github.com/jamiepine/voicebox) | Local TTS service and profile management | MIT |
| [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | Speech synthesis | Apache-2.0; check each model card |
| [OpenAI Whisper](https://github.com/openai/whisper) | English speech recognition | MIT |
| [Transformers](https://github.com/huggingface/transformers) | Whisper model runtime | Apache-2.0 |
| [RapidOCR](https://github.com/RapidAI/RapidOCR) | Visual-anchor OCR | Apache-2.0; OCR models may carry separate notices |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | RapidOCR inference | MIT |
| [FFmpeg](https://ffmpeg.org/) | Video and audio encoding | LGPL/GPL depending on the selected build |
| [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) | FFmpeg discovery and packaged binaries | BSD-2-Clause; bundled FFmpeg retains its own license |
| [PyTorch](https://github.com/pytorch/pytorch) | GPU inference | BSD-style |
| [FlashAttention](https://github.com/Dao-AILab/flash-attention) | Optional Qwen attention acceleration | BSD-3-Clause |
| [NumPy](https://github.com/numpy/numpy) | Numeric processing | BSD-3-Clause |
| [SciPy](https://github.com/scipy/scipy) | Audio resampling | BSD-3-Clause |
| [python-soundfile](https://github.com/bastibe/python-soundfile) | WAV input and output | BSD-3-Clause |
| [Pillow](https://github.com/python-pillow/Pillow) | Slide image processing | HPND |

Model files are downloaded at runtime and are not part of the OratorDeck source
distribution. Review the applicable model card before use or redistribution.
