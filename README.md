# Personal AI appliance

A version-controlled, in-place deployment for an Ubuntu Server AI host with an
RTX 3090. It keeps the existing native llama.cpp service and adds:

- LiteLLM as the authenticated OpenAI-compatible gateway on port 4000;
- Open WebUI as the human chat interface on port 3000;
- internal SearXNG JSON search for Open WebUI;
- an isolated, pinned OpenCode worker and filesystem batch queue.

LiteLLM and Open WebUI bind only to loopback and the host's dynamically detected
Tailscale IPv4. SearXNG has no host port. The batch worker has no inbound port,
Docker socket, host home, or broad filesystem mount.

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

For the known partial `/opt/ai-agent-stack` deployment, use migration instead:

```bash
sudo scripts/migrate --dry-run
sudo scripts/migrate
```

Migration inventories and backs up the old stack, preserves the Open WebUI
volume mounted at `/app/backend/data` when discoverable, stops only the replaced
tooling containers, and never changes `llama-server.service`.

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

For Aider:

```text
base URL: http://<server-hostname>:4000/v1
model: openai/glm-4.7-flash
API key: the LiteLLM master key
```

## Batch example

Copy `examples/batch-job`, choose a unique ID and `agent/...` branch, add the
exact repository URL to `/etc/ai-appliance/repositories.allow`, then:

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

The router keeps at most one model loaded at a time. Choosing another alias in
Open WebUI or OpenCode replaces the model occupying VRAM; catalogue entries and
cached model files remain available. `ai-model add` waits for llama.cpp's model
download to finish before exposing the new alias.

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
[security](docs/security.md), and [troubleshooting](docs/troubleshooting.md).
