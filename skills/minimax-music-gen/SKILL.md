---
name: minimax-music-gen
description: >
  This skill is retired and must not be used for music generation. Use this
  entry only to explain that the MiniMax Music CLI/API workflow is unavailable.
  Do not install or invoke retired MiniMax Music commands.
license: MIT
metadata:
  version: "1.2"
  category: creative
  status: retired
---

# Retired: MiniMax Music Generation

This skill is retained as a compatibility guard for existing installations, but
it no longer provides a working generation workflow.

MiniMax retired the Music command and SDK surface in
[MiniMax-AI/cli#239](https://github.com/MiniMax-AI/cli/pull/239). Current
`mmx-cli` releases do not expose the Music resource, so the former workflow
cannot succeed after a fresh CLI installation.

## Agent behavior

When a user asks for music generation, explain that this MiniMax skill is
retired and that no supported MiniMax music workflow is available here. Do not:

- install `mmx-cli` for the purpose of music generation;
- invoke retired Music subcommands;
- recommend pinning an old CLI release as a workaround; or
- claim that a song, instrumental track, or cover was generated.

Users may still use the repository's supported non-Music MiniMax skills. This
entry should be removed or replaced when MiniMax publishes a supported Music
integration.
