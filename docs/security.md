# Security and threat model

## Assets and adversaries

Protected assets include model/API keys, Git write credentials, private source,
Open WebUI chats, job prompts/artifacts, backups, host integrity, and the ability
to power off the server. Relevant threats include another Tailnet device,
compromised client credentials, malicious prompt content, a hostile repository
or dependency, agent mistakes, leaked logs/backups, and accidental public
exposure.

## Controls

- Client ports bind only to loopback and the detected Tailscale IPv4.
- LiteLLM requires a master key; Open WebUI requires its own account.
- SearXNG has no host port and enables JSON only on the Compose network.
- UFW is never flushed. When already active, installation adds only TCP
  3000/4000 rules on `tailscale0`.
- Containers drop capabilities, enable `no-new-privileges`, cap resources and
  logs, and use health checks. The worker root filesystem is read-only.
- The worker is non-root, has no inbound port, Docker socket, host root,
  administrator home, unrelated repository, or personal SSH directory.
- Each job gets one workspace and a read-only bundle. External-directory access,
  questions, subagents, and doom loops are denied in OpenCode permissions.
- Repository and check allow-lists, strict identifiers, no force-push, and a
  dedicated work branch constrain dispatcher actions.
- Secrets are generated outside Git, held in root/dedicated-group files, omitted
  from images/jobs, and redacted from captured output.
- Poweroff requires runner-produced terminal metadata, successful required push,
  an empty running queue, elapsed delay, and no inhibit file.
- The optional NUC power relay binds only to its detected Tailscale address and
  requires a random bearer token for every action/status request. Shutdown uses
  a pinned SSH host key and a dedicated public key restricted server-side to a
  single forced request command; it cannot create a general SSH session.
- Backups are mode 0700 and must be encrypted off-host.

## Residual risk

Tailscale is a reachability boundary, not authentication for LiteLLM or Open
WebUI. Docker is not a VM. OpenCode can edit the checked-out repository and run
tools; configured checks and package installers execute repository-controlled
code. A kernel/container escape, dependency compromise, resource exhaustion,
model prompt injection, or exfiltration over allowed outbound networking remains
possible.

Use a disposable VM and stronger egress controls for hostile repositories.
Review diffs and branches before merge. Use one repository-scoped deploy key per
trust domain, rotate it, and do not grant administrative SSH access. Keep the
host, Docker, and images patched through reviewed pin updates.

Open WebUI search has two stages: SearXNG returns result metadata/snippets, then
Open WebUI may retrieve page content from result URLs. Internal SearXNG does not
make arbitrary page-content retrieval internal or trusted. Retrieved pages can
contain prompt injection; keep SSRF protections enabled and treat cited content
as untrusted.
