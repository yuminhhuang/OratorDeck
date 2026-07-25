# Voicebox compatibility patch

OratorDeck's TTS client requires a slide-atomic batch endpoint that is not yet
part of upstream Voicebox.

`voicebox-qwen-batching.patch` is based on Voicebox commit:

```text
52f8d8dd387e4049c81ee97079d5f54e2e399b94
```

It adds:

- Qwen CustomVoice list batching.
- Optional FlashAttention 2 model loading with a safe fallback.
- An `/generate/atomic-batch` ZIP API that preserves item boundaries and order.
- Adaptive CUDA out-of-memory bisection without splitting an item.
- Optional batching for Voicebox's ordinary long-text chunk path.
- Regression tests for ordering and OOM recovery.

Apply it manually:

```bash
git clone https://github.com/jamiepine/voicebox.git vendor/voicebox
git -C vendor/voicebox checkout --detach \
  52f8d8dd387e4049c81ee97079d5f54e2e399b94
git -C vendor/voicebox apply ../../patches/voicebox-qwen-batching.patch
```

Or run:

```bash
scripts/setup-voicebox.sh
```

The patch includes and preserves the upstream Voicebox MIT notice through
`THIRD_PARTY_NOTICES.md`.
