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

The OpenCode version pinned by `OPENCODE_VERSION` in `versions.env` is validated
during the image build. The pinned CLI uses
`run --dangerously-skip-permissions --format json`; explicit deny rules remain
effective while approval prompts are skipped. They block
external-directory access, questions, subagents, and repeated identical tool
calls. The custom `appliance` provider uses `@ai-sdk/openai-compatible` against
LiteLLM.

The image does not contain credentials. A repository-scoped deploy key and
managed `known_hosts` are mounted read-only and copied into the ephemeral home
at runtime. Never mount a host SSH directory.
