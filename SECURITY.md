# Security Policy

## Reporting a vulnerability

Please use the repository's GitHub private vulnerability reporting feature.
Do not open a public issue for a vulnerability that could expose local files,
voice samples, generated media, service credentials, or arbitrary command
execution.

Include a minimal reproduction, affected revision, and expected impact. Avoid
including private presentation material in the report.

## Local-service boundary

The reference workflow binds Voicebox to `127.0.0.1`. Do not expose the
unmodified development server to an untrusted network. OratorDeck sends
speaker-note text and profile identifiers to the configured Voicebox URL, so a
remote endpoint must be treated as a recipient of that data.

Generated videos and speech may reveal sensitive source material. Review the
contents of `data/` before sharing or backing it up to a third-party service.
