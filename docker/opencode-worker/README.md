# OpenCode worker image

This pinned, non-root image supplies OpenCode, Git, SSH, and CA roots. It has no
daemon and exposes no port. The worker Compose service makes the root filesystem
read-only, drops all capabilities, prevents privilege escalation, and mounts
only one job workspace, one read-only job bundle, shared package cache, and two
narrow Git credential files.

The dispatcher invokes:

```sh
worker-entrypoint run glm-4.7-flash /job/instruction.md
```

The installed OpenCode `1.4.11` help was inspected during the build. This pin
uses `run --dangerously-skip-permissions --format json`; it does not accept the
newer `--auto` spelling shown in rolling documentation. Explicit deny rules
remain effective while approval prompts are skipped. They block
external-directory access, questions, subagents, and repeated identical tool
calls. The custom `appliance` provider uses `@ai-sdk/openai-compatible` against
LiteLLM.

The image does not contain credentials. A repository-scoped deploy key and
managed `known_hosts` are mounted read-only and copied into the ephemeral home
at runtime. Never mount a personal SSH directory.
