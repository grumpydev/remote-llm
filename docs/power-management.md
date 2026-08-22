# Remote power management

An always-on host on the same LAN acts as the Wake-on-LAN relay. Its API listens
on the relay host's detected Tailscale IPv4, requires a random bearer token for
wake, status, and shutdown, and sends the magic packet on its detected default
LAN. No LAN or Tailscale IP and no interface name is committed to this
repository.

```text
Phone or laptop on the Tailnet
    └──> relay host :8099
            ├──> UDP magic packet on the local LAN ──> AI server wired NIC
            ├──> ping / SSH / LiteLLM probes ──> staged status
            └──> restricted SSH over Tailscale :2222 ──> safe shutdown request
```

Shutdown uses a dedicated Ed25519 key whose server-side `authorized_keys` entry
is restricted to one forced command. It cannot open a general shell. That
command creates the same delayed shutdown request consumed by the batch-worker
poweroff timer, so running jobs and `/etc/ai-appliance/no-poweroff` inhibit both
remote and batch shutdown.

If Tailscale SSH is enabled, it [owns port 22 on the Tailscale
address](https://tailscale.com/docs/features/tailscale-ssh) and does not consult
OpenSSH `authorized_keys`. Authorization therefore configures
Tailscale Serve to forward tailnet-only TCP port 2222 to the host's standard
OpenSSH port 22. The relay uses port 2222, where the pinned host key and forced
command are enforced, while normal Tailscale SSH remains unchanged.

## Requirements

The AI server needs:

- the main appliance installed and healthy;
- wired Ethernet with firmware support for magic-packet wake from soft-off/S5;
- Tailscale and MagicDNS connectivity;
- a running OpenSSH server on port 22; and
- `ethtool` for persistent NIC configuration.

The relay host needs:

- Ubuntu, always on and connected to the same broadcast LAN as the AI server;
- Tailscale on the same Tailnet;
- Python 3, OpenSSH client, `ip`, `ping`, `curl`, and `openssl`; and
- `sudo` access for installation and service management.

Docker is required on the relay only when integrating a locally hosted Homepage
dashboard. The relay does not need a GPU or a copy of the AI server's model
files.

The maintainer runs the relay on a
[GMKtec G2 Intel N100 mini PC](https://minipc-review.com/en/gmktec-g2-mini-pc-the-most-balanced-alder-lake-n100-mini-pc-of-2025)
that is already always on for home automation and other lightweight services.
The separate RTX 3090 host is powered only when AI work is needed. The relay
software is intentionally small enough to share an existing home server; a
dedicated relay appliance is not required.

## Installed components

On the AI server, `configure-wol` installs `ai-wol.service`, records the NIC by
MAC rather than interface name, and reapplies `ethtool ... wol g` at every boot.
`authorize-power-relay` creates the dedicated `ai-power-relay` SSH account, one
forced `authorized_keys` command, a narrowly scoped sudoers entry, and the
tailnet-only port-2222 OpenSSH forward.

On the relay host, `install-power-relay` installs:

- `/opt/ai-power-relay` application files;
- root/group-readable configuration and credentials under
  `/etc/ai-power-relay`;
- `ai-power-relay.service`;
- the `ai-wake`, `ai-status`, and `ai-shutdown` commands; and
- a generated Homepage service snippet containing its backend bearer token.

The repository contains all server and relay implementation files. Generated
keys, tokens, detected addresses, interface details, and the Homepage snippet
remain local and are excluded from Git.

## Firmware and Ethernet prerequisites

On the AI machine, enable settings commonly named **Wake on LAN**, **Power on by
PCI-E/PCI**, or **Resume by LAN** in BIOS/UEFI. Disable ErP/deep S5 if it removes
standby power from the NIC. Use wired Ethernet; Wi-Fi WoL is not supported.

After the machine shuts down, its Ethernet link/activity LEDs should remain on.
Some firmware exposes separate settings for sleep and soft-off/S5; enable WoL
from S5 if available.

## Configure the AI server

Install `ethtool`, then let the appliance find the wired default-route NIC and
record its MAC:

```bash
sudo apt-get install ethtool
cd /opt/ai-appliance
sudo scripts/configure-wol
```

The systemd service resolves the interface by the configured MAC at every boot,
so an interface rename does not break it. Verify:

```bash
sudo scripts/configure-wol --check
systemctl status ai-wol.service
```

Record the printed MAC for the relay installer. Also transfer these two values
to the relay host through a secure channel:

```bash
sudo sed -n 's/^LITELLM_MASTER_KEY=//p' /opt/ai-appliance/.env
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
```

The first is a secret. The SSH host key is public and lets the relay pin the AI
server rather than trusting first use.

## Install the relay host

Clone this repository on the always-on relay host, save the LiteLLM key and
server host public key into temporary root-readable files, then run:

```bash
git clone <this-repository-url> ~/src/ai-appliance
cd ~/src/ai-appliance

sudo scripts/install-power-relay \
  --target-mac 00:11:22:33:44:55 \
  --target-host ai-server \
  --litellm-key-file ./litellm.key \
  --host-key-file ./ai-server-host-key.pub \
  --admin-user "$USER"
```

Use the AI server's Tailscale/MagicDNS hostname for `--target-host`. The
installer detects the relay host's Tailscale address, default LAN interface, and
broadcast address; creates a service account, token and SSH key; enables a
systemd relay; and adds a narrowly scoped UFW rule on `tailscale0` if UFW is
already active. Rerunning it reconciles configuration while preserving its
token and SSH identity.

The LiteLLM key file is required only on the first install or when replacing
the stored key. The host-key file is required initially so shutdown never falls
back to trust-on-first-use. On later reconciliations, omit both file arguments
to retain the installed copies.

Copy the relay public key printed by the installer back to the AI server and
authorize it. It can also be read later from
`/etc/ai-power-relay/id_ed25519.pub` on the relay host:

```bash
sudo /opt/ai-appliance/scripts/authorize-power-relay \
  --key-file ./relay-host.pub
```

Rerunning authorization replaces any matching unrestricted or stale entry with
exactly one forced-command entry; it never preserves broader access for that
relay key.

Delete temporary copies of the LiteLLM key after installation. Log out and back
in on the relay host to receive `ai-power-relay` group access.

## Validate the complete path

Before testing shutdown, confirm status from the relay. Use `sudo` until the
new group membership is active:

```bash
sudo ai-status
sudo ai-status --model
```

Then perform one attended power cycle. Replace `ai-server` with the exact value
passed to `--target-host`:

```bash
sudo ai-shutdown --confirm ai-server
# Wait for the idle gate and operating system to shut the server down.
sudo ai-status
sudo ai-wake
# During boot, repeat this to observe the staged state transitions.
sudo ai-status
```

After the host reaches `litellm-online`, `sudo ai-status --model` can trigger the
configured model load and wait for `model-ready`. Test the first cycle while you
still have physical access: a successful API response means the relay sent a
magic packet, not that firmware accepted it.

## Commands and states

On the relay host:

```bash
ai-wake
ai-status
ai-status --model
ai-shutdown --confirm ai-server
```

`ai-status` is non-invasive and reports:

- `powered-off`: no ping, SSH, or LiteLLM response;
- `booting`: the host responds but SSH is not ready;
- `host-online`: SSH is ready but LiteLLM is not;
- `litellm-online`: authenticated model routing is available;
- `model-ready`: an explicit `ai-status --model` completion succeeded.

The normal Homepage poll never loads a model into VRAM. Only the explicit
`--model` probe does that. A large model can take several minutes to become
ready after a cold boot, so readiness probes allow up to 900 seconds by default.
In an interactive terminal, `ai-status --model` updates an elapsed-time status
line while the completion request is actively triggering or waiting for that
load; the final JSON remains clean stdout for scripts.

Remote shutdown is delayed by 30 seconds and uses the existing idle gate. It
will not power off while a batch job is running or when the inhibit file exists:

```bash
sudo touch /etc/ai-appliance/no-poweroff
sudo rm /etc/ai-appliance/no-poweroff
```

## Homepage

The relay installer writes a secret-bearing snippet to:

```text
/etc/ai-power-relay/homepage-services.yaml
```

Install it into a standard Homepage deployment without printing the token:

```bash
sudo scripts/install-homepage-widget
```

The installer backs up `/opt/homepage/config/services.yaml`, atomically replaces
only its marked `AI Appliance` block, preserves all other dashboard content,
and restarts the `homepage` container. If UFW is active, it detects Homepage's
Docker bridge and adds a narrow bridge-subnet rule to only the relay's Tailscale
address and TCP port, then verifies connectivity from inside the container. Use
`--services-file` or `--container` for non-standard deployments. The custom API
widget polls status with an authorization header. Clicking the service opens
the relay's small web UI;
enter the relay token once on the phone (stored in that browser's local storage)
to reveal status and use Wake or Safe shutdown.

The same managed group includes an **AI Chat** card linking to Open WebUI via
the AI server's configured Tailscale/MagicDNS hostname. The default port is
3000; pass `--open-webui-port PORT` to `install-power-relay` when the appliance
uses a different port. The link contains no credential or fixed IP address.

Retrieve the token without exposing other configuration:

```bash
sudo cat /etc/ai-power-relay/token
```

Homepage has no built-in authentication layer. Keep Homepage and the relay
behind Tailscale and/or an authenticated reverse proxy. Do not commit the
generated snippet because it contains the relay bearer token.

The relay web UI automatically recognizes direct Tailscale source addresses and
uses that authenticated Tailnet path without asking the user to copy the bearer
token. Same-origin UI requests carry a non-simple header so a third-party web
page cannot trigger actions through browser CSRF. CLI, Homepage backend, and LAN
requests continue to require the bearer token; it is never placed in the UI
link, page source, or browser history.

With Tailscale active on a phone, open the Homepage dashboard and use **AI
Appliance Power** for status, wake, and safe shutdown, or **AI Chat** to open
Open WebUI. Direct access to `http://<relay-tailscale-address>:8099/` provides
the same power controls without Homepage.

## Troubleshooting

```bash
# AI server
sudo ethtool "$(ip -4 route show default | awk '{print $5; exit}')"
systemctl status ai-wol.service ai-poweroff-check.timer
sudo scripts/poweroff-when-idle --dry-run

# Relay host
systemctl status ai-power-relay.service
journalctl -u ai-power-relay.service -n 100 --no-pager
curl "http://$(tailscale ip -4 | head -n1):8099/healthz"
```

If wake works from suspend but not full poweroff, revisit S5/ErP firmware
settings. If status remains `powered-off`, verify MagicDNS and the target
hostname. If shutdown fails, compare the AI server's current SSH host-key
fingerprint with the pinned relay file and confirm the relay public key is still
present in the dedicated user's `authorized_keys`.
