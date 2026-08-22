# Architecture

## Interactive path

Clients reach LiteLLM on TCP 4000. LiteLLM is the sole normal API gateway and
forwards the stable `glm-4.7-flash` alias to native llama.cpp at
`host.docker.internal:8080/v1`. Open WebUI reaches only LiteLLM and is exposed on
TCP 3000. Both host ports bind to loopback and the current Tailscale IPv4.
SearXNG has no published port and is reachable only on the Compose network.

```text
Tailscale clients ──> LiteLLM :4000 ──> native llama.cpp :8080 ──> NVIDIA GPU
                           ^
Open WebUI :3000 ──────────┘
       └──────────────────────> SearXNG :8080 (internal only)
```

Optional power control adds a separate path. An always-on LAN peer exposes an
authenticated relay only on its Tailscale address, sends WoL locally, checks
the AI host by MagicDNS name, and uses a pinned, forced-command SSH key to place
a delayed request into the appliance's existing safe-poweroff gate.

Docker reaches the native provider through the Linux
`host.docker.internal:host-gateway` mapping. The deployment checks both the
provider model list and an authenticated LiteLLM chat completion before
declaring the stack healthy. When UFW is active, the installer permits provider
traffic only on the appliance's Docker bridge interface; port 8080 is not opened
to LAN or Tailscale clients.

## Batch path

The host dispatcher atomically renames one job directory from `queue` to
`running`, validates it, creates a dedicated workspace, and launches the pinned
worker container with only that workspace, job context, cache, and narrowly
scoped credential files mounted. OpenCode runs non-interactively through
LiteLLM. The host dispatcher owns lifecycle policy: checks, commits, dedicated
branch pushes, reports, cancellation, and optional shutdown.

```text
queue -> host dispatcher -> restricted OpenCode container -> LiteLLM
                    |
                    +-> workspace, checks, artifacts, commit, branch push
                    +-> completed | failed | cancelled
```

The worker gets no Docker socket, host root, administrator home, unrelated
repositories, or inbound port. Capabilities are dropped and
`no-new-privileges` is enabled. Internet access is permitted because jobs may
clone repositories, install packages, and retrieve documentation.

## State and trust boundaries

- `/opt/ai-appliance`: deployed immutable-ish application files and rendered
  configuration.
- Docker volumes: Open WebUI data and SearXNG runtime data.
- `/etc/ai-appliance`: root-owned secrets and repository allow-list.
- `/srv/ai-jobs`: queue, workspaces, cache, and terminal job artifacts.
- `/var/backups/ai-appliance`: sensitive backups; root-readable only.
- `/usr/local/bin/llama-server`: externally maintained and never replaced.
- `llama-server.service`: left untouched by installation and migration; the
  explicit `ai-model enable` action adds only an appliance-owned router
  `ExecStart` drop-in.

Tailscale limits network reachability but does not replace LiteLLM authentication
or Open WebUI accounts. Repository contents, dependency installers, tests, and
agent-generated commands are untrusted code. Use a VM for hostile repositories.

## Failure and rollback model

Migration inventories and backs up the old stack, detects the existing Open
WebUI volume, and stops only named tooling containers. A failed cutover removes
only newly created containers, restores the deployed configuration backup, and
restarts previously running containers where possible. Volumes are never
silently deleted. Version rollback restores the previous version lock and
configuration, then health-checks the reverted stack. Native llama.cpp remains
untouched.
