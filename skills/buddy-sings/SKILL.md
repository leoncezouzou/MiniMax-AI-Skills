---
name: buddy-sings
description: >
  This skill is retired and must not be used for music generation. Use this
  entry only to explain that the MiniMax Music workflow behind buddy-sings is
  unavailable. Do not install or invoke retired MiniMax Music commands.
license: MIT
metadata:
  version: "1.2"
  category: creative
  status: retired
---

# Retired: buddy-sings

This skill is retained as a compatibility guard for existing installations,
but it no longer provides a working way for a Claude Code pet to sing.

The skill depended on the MiniMax Music command and SDK surface that was
retired in
[MiniMax-AI/cli#239](https://github.com/MiniMax-AI/cli/pull/239). Current
`mmx-cli` releases do not expose that resource.

## Agent behavior

When a user asks the buddy to sing, explain that this skill is retired and that
no supported MiniMax music workflow is available here. Do not install the CLI
for music generation, invoke retired Music subcommands, recommend an old CLI
release as a workaround, or claim that audio was generated.

This entry should be removed or replaced when MiniMax publishes a supported
Music integration.
