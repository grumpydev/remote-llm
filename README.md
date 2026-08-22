# Self-hosted AI appliance

This repository turns an Ubuntu machine with an NVIDIA GPU and native llama.cpp
into a private, remotely operated AI appliance. It provides browser chat, an
OpenAI-compatible API, local and unattended coding agents, web search,
multi-model routing, and safe remote power control. A laptop or phone reaches
the appliance through Tailscale; no service needs to be exposed to the public
Internet.

## What it provides

| Capability | What it is useful for |
| --- | --- |
| GPT-style chat | Open WebUI provides accounts, chat history, model selection, citations, and SearXNG-backed web search. |
| OpenAI-compatible API | LiteLLM gives tools such as Aider and other API clients one authenticated endpoint for the local models. |
| Local coding agent | `ai-opencode` runs the pinned OpenCode worker against a selected local directory without mounting the rest of the host. |
| Unattended coding agents | A filesystem queue runs isolated coding jobs, captures reports and diffs, performs approved checks, and can push only a dedicated branch. |
| Multiple local models | `ai-model` downloads GGUF models, keeps stable aliases, and switches the single loaded model on demand. |
| Private remote access | Open WebUI and LiteLLM bind to loopback and the machine's detected Tailscale address. SearXNG remains internal. |
| Remote start and stop | An always-on Ubuntu relay on the same LAN provides authenticated Wake-on-LAN, staged readiness status, and policy-gated shutdown from a phone or CLI. |
| Operations and recovery | Pinned images, diagnostics, backups, updates, rollback, secret rotation, and migration tooling keep the deployment reproducible. |

## Deployment shape

The main AI server owns the GPU, native llama.cpp service, Docker application,
model catalogue, and coding-job queue. An optional low-power relay host stays on
the same wired LAN so it can wake the server after shutdown. Both hosts join the
same Tailnet.

```text
Phone / laptop over Tailscale
    ├──> Open WebUI chat :3000 ──> LiteLLM :4000 ──> llama.cpp ──> GPU
    ├──> OpenAI-compatible clients ────────────────────┘
    ├──> SSH / ai-opencode / queued coding jobs
    └──> Relay UI or CLI ──> Wake-on-LAN / status / safe shutdown
                              └──> Homepage links to chat and power
```

LiteLLM and Open WebUI bind only to loopback and the host's dynamically detected
Tailscale IPv4. SearXNG has no host port. The batch worker has no inbound port,
Docker socket, host home, or broad filesystem mount. The relay binds only to its
detected Tailscale IPv4 and holds a dedicated SSH key that is restricted on the
AI server to requesting safe shutdown.

### Maintainer's deployment

In the maintainer's setup, the always-on relay is a
[GMKtec G2 mini PC with an Intel N100](https://minipc-review.com/en/gmktec-g2-mini-pc-the-most-balanced-alder-lake-n100-mini-pc-of-2025).
It is a small, low-power machine that already runs home-automation and other
lightweight household services, so the relay adds very little overhead and does
not need a dedicated computer. The much more power-hungry RTX 3090 AI server is
normally shut down and is woken only when chat, model inference, or coding-agent
work is needed. When work is complete, the same relay requests a policy-gated
shutdown.

This is an example rather than a hardware requirement. Any always-on Ubuntu host
on the same LAN, with Tailscale connectivity and the ability to send a WoL magic
packet, can fill the relay role.

## Server quick start

Review [installation](docs/installation.md), then on your AI server:

```bash
git clone <this-repository-url> ~/src/ai-appliance
cd ~/src/ai-appliance
sudo scripts/doctor
sudo scripts/install
scripts/status
scripts/doctor
```

When replacing an earlier `/opt/ai-agent-stack` deployment, use migration
instead:

```bash
sudo scripts/migrate --dry-run
sudo scripts/migrate
```

Migration inventories and backs up the old stack, preserves the Open WebUI
volume mounted at `/app/backend/data` when discoverable, stops only the replaced
tooling containers, and never changes `llama-server.service`.

To add remote start, staged status, safe shutdown, and optional Homepage cards,
follow the complete [remote power management guide](docs/power-management.md)
on the AI server and an always-on Ubuntu relay host.

## Endpoints

| Purpose | URL | Authentication |
| --- | --- | --- |
| LiteLLM | `http://<server-hostname>:4000/v1` | Bearer master key |
| Open WebUI | `http://<server-hostname>:3000` | Open WebUI account |
| llama.cpp provider | `http://127.0.0.1:8080/v1` | Provider key; not a normal client endpoint |
| SearXNG | Compose network only | Not externally exposed |

Retrieve the LiteLLM key without printing other secrets:

```bash
sudo sed -n 's/^LITELLM_MASTER_KEY=//p' /opt/ai-appliance/.env
```

Open `http://<server-hostname>:3000` from a Tailnet-connected browser for the
ChatGPT-style interface. The same hostname on port 4000 serves API clients.

For Aider:

```text
base URL: http://<server-hostname>:4000/v1
model: openai/glm-4.7-flash
API key: the LiteLLM master key
```

## Remote power and dashboard

After completing [power management setup](docs/power-management.md), the
always-on relay provides:

```bash
ai-wake
ai-status
ai-status --model
ai-shutdown --confirm <server-hostname>
```

Status distinguishes powered off, booting, host online, LiteLLM online, and
model ready. Shutdown is a delayed request, not an unrestricted remote shell or
immediate power cut: running batch work and the administrator inhibit file can
block it safely. The optional Homepage integration adds **AI Chat** and **AI
Appliance Power** cards for phone use over Tailscale.

## Remote and unattended coding jobs

Connect to the AI server over Tailscale SSH, copy `examples/batch-job`, choose a
unique ID and `agent/...` branch, add the exact repository URL to
`/etc/ai-appliance/repositories.allow`, then:

```bash
sudo scripts/submit-job ./my-job
scripts/list-jobs
sudo scripts/run-next-job
```

A push targets only `HEAD:refs/heads/<work_branch>` and never merges or
force-pushes. See [batch jobs](docs/batch-jobs.md).

## Models and interactive OpenCode

After installation, enable llama.cpp router mode once:

```bash
sudo ai-model enable
```

Add a Hugging Face GGUF quantization and keep it selectable alongside the
default model:

```bash
sudo ai-model add \
  --alias qwen-coder \
  --source owner/model-GGUF:Q4_K_M \
  --context 32768
```

The router preloads the default model during boot and keeps at most one model
loaded at a time. Choosing another alias in Open WebUI or OpenCode replaces the
model occupying VRAM; catalogue entries and cached model files remain
available. `ai-model add` waits for llama.cpp's model download to finish before
exposing the new alias.

Run interactive OpenCode in the current repository:

```bash
ai-opencode .
ai-opencode --model qwen-coder .
```

Only the selected directory is writable inside the worker. See
[model routing](docs/models.md) and [batch jobs](docs/batch-jobs.md).

## Operations

```bash
scripts/status
scripts/doctor
sudo scripts/update --check
sudo scripts/update --apply
sudo scripts/backup
sudo scripts/restore /var/backups/ai-appliance/<timestamp>
sudo scripts/rollback
sudo scripts/add-model --help
sudo scripts/remove-model --help
ai-model --help
ai-opencode --help
make test
```

Start with [architecture](docs/architecture.md), [operations](docs/operations.md),
[security](docs/security.md), [power management](docs/power-management.md), and
[troubleshooting](docs/troubleshooting.md).

## Public repository checks

`make test` checks shell/Python/configuration behaviour, moving container tags,
and user-specific absolute home paths. Before publishing, maintainers can also
provide a local, case-insensitive deny pattern without committing private names:

```bash
AI_PUBLIC_PRIVATE_PATTERN='username|private-hostname' make test
```

Generated secrets, runtime configuration, backups, Python caches, and
`docs/build-report.md` are ignored by Git. Review `git status` and the staged
diff before every public push; never add generated relay snippets because they
contain a bearer token.
