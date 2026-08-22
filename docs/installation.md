# Installation

## Prerequisites

- Ubuntu Server amd64, Docker Engine, and Docker Compose v2.
- Working NVIDIA driver/CUDA and native `llama-server.service`.
- Working Tailscale connection and a `100.x.y.z` IPv4.
- `/usr/local/bin/llama-server`, `/usr/local/sbin/run-llama-server`,
  `/etc/llama-server.env`, and `/etc/llama-server.api-key` already configured.
- Native provider healthy at `http://127.0.0.1:8080/v1`, with model ID
  `glm-4.7-flash`.
- TCP 3000 and 4000 free on loopback and the Tailscale address.

The installer deliberately does not install or update Ubuntu, NVIDIA, CUDA,
llama.cpp, or the GGUF.

## Preflight and install

```bash
cd ~/src/ai-appliance
sudo scripts/doctor
sudo scripts/install --dry-run
sudo scripts/install
```

The initial pre-install doctor will report the not-yet-installed stack as failed;
use the OS, Docker, Tailscale, native llama.cpp, disk, and GPU lines as preflight
evidence. Installation:

1. detects the Tailscale IPv4;
2. creates the `ai-appliance` group and adds the account detected from
   `SUDO_USER` (or supplied with `--admin-user`);
3. deploys repository files to `/opt/ai-appliance`;
4. generates missing 256-bit secrets and imports the llama.cpp API key;
5. creates/preserves the external Open WebUI volume;
6. creates queue/policy/credential paths;
7. validates ports and rendered Compose/configuration;
8. starts SearXNG, LiteLLM, then Open WebUI;
9. runs live end-to-end checks;
10. enables the queue path unit and safe-poweroff timer;
11. installs the `ai-model`, `ai-opencode`, and `ai-rotate-litellm-key` command
    links;
12. if UFW is active, permits TCP 8080 only from the appliance Docker bridge
    and TCP 3000/4000 only on the Tailscale interface.

Log out and back in after first installation so the `ai-appliance` group takes
effect. Access to Docker still follows the server's Docker group policy.

The native llama.cpp service remains unchanged until the administrator
explicitly runs `sudo ai-model enable`. That command verifies router support
before installing its reversible systemd `ExecStart` drop-in.

## Credentials

Files under `/etc/ai-appliance` and `/opt/ai-appliance/.env` are root or
`ai-appliance` group readable. The installer passes that group's numeric GID as a
supplementary worker group so the non-root process can copy its read-only,
repository-scoped credential files. Do not paste their contents into job
manifests.

For a GitHub SSH deploy key:

```bash
sudo install -m 0600 ./repository-deploy-key /etc/ai-appliance/git_deploy_key
ssh-keyscan -t ed25519 github.com |
  sudo tee /etc/ai-appliance/known_hosts >/dev/null
sudo chmod 0640 /etc/ai-appliance/known_hosts
```

Verify the fingerprint out of band before trusting `ssh-keyscan`. Give the key
write permission only on repositories that jobs may push to. Add exact URLs or
deliberately narrow globs to:

```text
/etc/ai-appliance/repositories.allow
```

## Open WebUI first login

Open `http://<server-hostname>:3000`, create the initial administrator, verify
`glm-4.7-flash`, then disable new account registration in the Open WebUI admin
settings. This repository intentionally does not invent or depend on an
undocumented signup environment variable.

Open WebUI persists many settings as ConfigVars in its database. Saved UI values
can override environment variables after first start. If model routing or search
does not reflect Compose, inspect the admin Connections and Web Search settings.

## Optional trusted LAN

The supported default is loopback plus Tailscale. To add a trusted LAN, add an
explicit bind and a narrowly scoped UFW source-CIDR rule after threat-model
review. Do not use `0.0.0.0` and do not expose either port through the router.
