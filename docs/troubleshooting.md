# Troubleshooting

Run `scripts/doctor` first. It returns non-zero while a critical path is broken.

## llama.cpp key or health fails

```bash
sudo systemctl status llama-server.service
sudo test -s /etc/llama-server.api-key
sudo curl -H "Authorization: Bearer $(sudo cat /etc/llama-server.api-key)" \
  http://127.0.0.1:8080/v1/models
```

Installation must run as root so it can import the native key. It never changes
the service's account or permissions. If the binary reports HTTPS unsupported,
that is native llama.cpp maintenance outside this stack; do not point LiteLLM at
an HTTPS provider until the binary is built with OpenSSL support.

## Docker cannot reach the host provider

Confirm Compose contains:

```yaml
extra_hosts:
  - host.docker.internal:host-gateway
```

Then inspect LiteLLM logs and the host listener:

```bash
sudo ss -ltnp 'sport = :8080'
sudo docker compose --project-directory /opt/ai-appliance \
  --env-file /opt/ai-appliance/versions.env \
  --env-file /opt/ai-appliance/.env logs litellm
```

llama.cpp must listen on an address reachable through the Docker host gateway,
not exclusively on a namespace-inaccessible loopback. Prefer firewalling that
provider path over publishing port 8080 to clients.

If native requests work but LiteLLM reports a connection timeout to
`host.docker.internal:8080`, inspect the appliance bridge and its UFW rule:

```bash
network_id="$(sudo docker network inspect ai-appliance_internal --format '{{.Id}}')"
bridge="br-${network_id:0:12}"
sudo ufw status | grep -F "${bridge}"
```

Rerunning `sudo scripts/install` reconciles the bridge-scoped port 8080 rule.

## Web search finds URLs but reports no sources

The appliance defaults `BYPASS_WEB_SEARCH_WEB_LOADER=true`, which supplies
SearXNG titles, URLs, and snippets directly instead of fetching arbitrary
result pages. Many sites block automated clients, require JavaScript, or contain
untrusted content, so snippet mode is the predictable and safer default.

Open WebUI ConfigVars saved in its database take precedence over environment
defaults. For an existing database, open **Admin Panel → Settings → Web Search**,
enable **Bypass Web Loader**, and save once.

## Open WebUI cannot see the model

Check LiteLLM first, then the container-network check in doctor. Open WebUI
database ConfigVars can override environment variables. In its admin UI inspect
Connections, remove stale direct llama.cpp/Ollama endpoints, and keep only
`http://litellm:4000/v1` with the LiteLLM key.

## Search fails

SearXNG must allow JSON:

```yaml
search:
  formats:
    - html
    - json
```

Doctor queries it from the Open WebUI container network. If JSON search works but
page content does not, debug Open WebUI's page loader separately; search-result
retrieval and result-page content retrieval are different network operations.
Saved Web Search ConfigVars can override Compose values.

## Port conflict

Installation prints the conflicting listener and stops before cutover:

```bash
sudo ss -ltnp 'sport = :3000'
sudo ss -ltnp 'sport = :4000'
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

Use `scripts/migrate` for the known legacy stack. Do not kill unrelated services.

## `/opt` cannot be inspected

The installer creates `/opt/ai-appliance` mode 0755, while `.env`, runtime
configuration, and credentials remain restricted. Check each path component:

```bash
namei -l /opt/ai-appliance
```

## Worker clone/push fails

Verify the exact URL is allow-listed, the deploy key has repository scope and
write access, and `known_hosts` contains a verified key. Review `git-prepare.log`
and `push.log`; secrets should be redacted. The worker uses strict host-key
checking and never falls back to a personal SSH key.

## Job remains running

```bash
systemctl status ai-batch-worker.service
journalctl -u ai-batch-worker.service
sudo scripts/cancel-job JOB_ID
```

Cancellation is cooperative at the dispatcher subprocess boundary and is polled
several times per second. If Docker itself is wedged, stop the systemd service,
inspect the worker container, and preserve the running bundle before intervention.

## Shutdown did not occur

```bash
sudo scripts/poweroff-when-idle --dry-run
ls -l /etc/ai-appliance/no-poweroff /srv/ai-jobs/shutdown.request
systemctl status ai-poweroff-check.timer
```

A failed required push, running job, inhibit file, unelapsed delay, missing
metadata, or metadata mismatch blocks shutdown by design.
