# Operations

## Status and diagnostics

```bash
scripts/status
scripts/doctor
journalctl -u ai-batch-worker.service
docker compose \
  --project-directory /opt/ai-appliance \
  --env-file /opt/ai-appliance/versions.env \
  --env-file /opt/ai-appliance/.env ps
```

`doctor` prints PASS/WARN/FAIL and exits non-zero for critical failures. It
checks OS/architecture, Docker/Compose, Tailscale, UFW, native llama.cpp and
model, host-to-container routing through the live stack, authenticated LiteLLM,
Open WebUI, internal SearXNG JSON, policy/credential paths, queue disk space, Git,
GPU visibility, and bindings.

## Back up, restore, rollback

```bash
backup="$(sudo scripts/backup)"
sudo scripts/restore "${backup}"
sudo scripts/rollback
```

Backups contain secrets, configuration, and Open WebUI data. They are mode 0700
and belong in encrypted storage. Restore is explicitly destructive to the
selected Open WebUI volume: it stops the appliance, replaces that volume's
contents from the chosen archive, starts the stack, and validates it. This
destruction occurs only after the explicit `restore` command.

Rollback chooses the newest backup if no path is given. Keep the backup path
printed by every update.

## Updates

Versions live in `versions.env`; no service uses `latest` or an unversioned
`main` tag.

```bash
sudo scripts/update --check
sudo scripts/update --apply
```

Apply creates a configuration backup, installs the repository version lock,
pulls images, recreates changed services, and validates. A failed validation
restores the prior configuration. Review upstream release/security notes before
changing a pin.

Native llama.cpp is separate. A conservative manual native update keeps the old
binary:

```bash
sudo install -m 0755 /usr/local/bin/llama-server \
  /usr/local/bin/llama-server.previous
sudo install -m 0755 ./new-llama-server /usr/local/bin/llama-server
sudo systemctl restart llama-server.service
curl -fsS http://127.0.0.1:8080/v1/models
```

Rollback:

```bash
sudo install -m 0755 /usr/local/bin/llama-server.previous \
  /usr/local/bin/llama-server
sudo systemctl restart llama-server.service
```

Include the API key header in the curl command when required. Do not combine
native maintenance with `scripts/update`.

## Key rotation

Generate a replacement LiteLLM key in a mode-0600 file and apply it without
printing it:

```bash
sudo ai-rotate-litellm-key --key-file ./new-litellm.key
```

The command atomically updates `.env`, recreates LiteLLM and Open WebUI, and
validates the new credential. If validation fails it restores the previous key
and services. Update clients and the optional power relay from the same key
file, then securely delete temporary copies. Rotating `WEBUI_SECRET_KEY` may
invalidate sessions and still requires a reviewed manual change and backup.

## Idle shutdown

A job can request shutdown. The runner writes `/srv/ai-jobs/shutdown.request`
only after artifacts are flushed and policy conditions are satisfied. A timer
checks the delay, terminal metadata, required push result, running directory,
and inhibit file, calls `sync`, then powers off.

Create `/etc/ai-appliance/no-poweroff` to inhibit all job-requested shutdowns.
Preview an eligible request:

```bash
sudo scripts/poweroff-when-idle --dry-run
```

Authenticated remote shutdown and batch shutdown share this gate and request
format. See [remote power management](power-management.md) for WoL relay setup,
status states, restricted-key authorization, and Homepage integration.
