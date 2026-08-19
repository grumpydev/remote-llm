# Remote power management

The always-on NUC is the only Wake-on-LAN relay. Its API listens on the NUC's
detected Tailscale IPv4, requires a random bearer token for wake, status, and
shutdown, and sends the magic packet on its detected default LAN. No LAN or
Tailscale IP and no interface name is committed to this repository.

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

Record the printed MAC for the NUC installer. Also transfer these two values to
the NUC through a secure channel:

```bash
sudo sed -n 's/^LITELLM_MASTER_KEY=//p' /opt/ai-appliance/.env
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
```

The first is a secret. The SSH host key is public and lets the relay pin the AI
server rather than trusting first use.

## Install the NUC relay

Clone this repository on the always-on relay host, save the LiteLLM key and
server host public key into temporary root-readable files, then run:

```bash
sudo scripts/install-power-relay \
  --target-mac 00:11:22:33:44:55 \
  --target-host ai-server \
  --litellm-key-file ./litellm.key \
  --host-key-file ./ai-server-host-key.pub \
  --admin-user "$USER"
```

Use the AI server's Tailscale/MagicDNS hostname for `--target-host`. The
installer detects the NUC's Tailscale address, default LAN interface, and
broadcast address; creates a service account, token and SSH key; enables a
systemd relay; and adds a narrowly scoped UFW rule on `tailscale0` if UFW is
already active. Rerunning it reconciles configuration while preserving its
token and SSH identity.

Copy the relay public key printed by the installer back to the AI server and
authorize it:

```bash
sudo /opt/ai-appliance/scripts/authorize-power-relay \
  --key-file ./relay-host.pub
```

Rerunning authorization replaces any matching unrestricted or stale entry with
exactly one forced-command entry; it never preserves broader access for that
relay key.

Delete temporary copies of the LiteLLM key after installation. Log out and back
in on the NUC to receive `ai-power-relay` group access.

## Commands and states

On the NUC:

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

The NUC installer writes a secret-bearing snippet to:

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

## Troubleshooting

```bash
# AI server
sudo ethtool "$(ip -4 route show default | awk '{print $5; exit}')"
systemctl status ai-wol.service ai-poweroff-check.timer
sudo scripts/poweroff-when-idle --dry-run

# NUC
systemctl status ai-power-relay.service
journalctl -u ai-power-relay.service -n 100 --no-pager
curl "http://$(tailscale ip -4 | head -n1):8099/healthz"
```

If wake works from suspend but not full poweroff, revisit S5/ErP firmware
settings. If status remains `powered-off`, verify MagicDNS and the target
hostname. If shutdown fails, compare the AI server's current SSH host-key
fingerprint with the pinned NUC file and confirm the relay public key is still
present in the dedicated user's `authorized_keys`.
