# In-place migration

Use migration when `/opt/ai-agent-stack`, old tooling containers, or an existing
Open WebUI volume may be present:

```bash
cd ~/src/ai-appliance
sudo scripts/migrate --dry-run
sudo scripts/migrate
```

The command inventories `open-webui`, `searxng`, `open-terminal`, and `litellm`,
and volumes named `open-webui-data` or ending `_open-webui-data`. It prefers the
volume actually mounted by `open-webui` at `/app/backend/data`.

Before cutover it creates a sensitive root-only backup under
`/var/backups/ai-appliance`. It stops only the four replaced tooling container
names. It never stops, restarts, edits, or updates `llama-server.service`.

The new stack uses generated Compose names, avoiding name collisions with the
legacy containers. After startup it checks:

- native llama.cpp model list;
- authenticated LiteLLM model list;
- model visibility from the Open WebUI container network;
- SearXNG JSON from the Open WebUI container network;
- Open WebUI health and Tailscale binding.

If cutover fails, the trap stops the new Compose application and restarts the
previously running legacy containers where safe. It retains the backup and does
not delete any volume. A newly created empty `open-webui-data` volume may remain
when another preserved volume is selected; this is intentional and can be
removed manually only after inspection.

After a successful migration, verify old chats and accounts before considering
legacy configuration cleanup:

```bash
scripts/status
scripts/doctor
docker volume ls
sudo ls -la /var/backups/ai-appliance
```

