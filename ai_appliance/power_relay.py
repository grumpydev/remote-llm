"""Authenticated Wake-on-LAN relay and staged appliance status API."""
from __future__ import annotations

import argparse
import hmac
import html
import ipaddress
import json
import os
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$")


@dataclass(frozen=True)
class Config:
    listen_host: str
    port: int
    token: str
    target_mac: str
    target_host: str
    broadcast: str
    litellm_port: int
    litellm_key: str
    ssh_user: str
    ssh_key: Path
    known_hosts: Path
    model_ready_timeout: int = 900

    @classmethod
    def from_env(cls) -> "Config":
        token = Path(os.environ["AI_RELAY_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
        litellm_key = Path(os.environ["AI_TARGET_LITELLM_KEY_FILE"]).read_text(
            encoding="utf-8"
        ).strip()
        config = cls(
            listen_host=os.environ["AI_RELAY_LISTEN_HOST"],
            port=int(os.environ.get("AI_RELAY_PORT", "8099")),
            token=token,
            target_mac=os.environ["AI_TARGET_MAC"].lower(),
            target_host=os.environ["AI_TARGET_HOST"],
            broadcast=os.environ["AI_RELAY_BROADCAST"],
            litellm_port=int(os.environ.get("AI_TARGET_LITELLM_PORT", "4000")),
            litellm_key=litellm_key,
            ssh_user=os.environ.get("AI_SHUTDOWN_SSH_USER", "ai-power-relay"),
            ssh_key=Path(os.environ["AI_SHUTDOWN_SSH_KEY"]),
            known_hosts=Path(os.environ["AI_SHUTDOWN_KNOWN_HOSTS"]),
            model_ready_timeout=int(os.environ.get("AI_MODEL_READY_TIMEOUT", "900")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        ipaddress.ip_address(self.listen_host)
        ipaddress.ip_address(self.broadcast)
        if not 1024 <= self.port <= 65535 or not 1 <= self.litellm_port <= 65535:
            raise ValueError("invalid port")
        if not 1 <= self.model_ready_timeout <= 3600:
            raise ValueError("invalid model readiness timeout")
        if len(self.token) < 32 or not MAC_RE.fullmatch(self.target_mac):
            raise ValueError("invalid token or MAC")
        if not HOST_RE.fullmatch(self.target_host) or not HOST_RE.fullmatch(self.ssh_user):
            raise ValueError("invalid target host or SSH user")


def magic_packet(mac: str) -> bytes:
    raw = bytes.fromhex(mac.replace(":", ""))
    if len(raw) != 6:
        raise ValueError("invalid MAC")
    return b"\xff" * 6 + raw * 16


class Relay:
    def __init__(self, config: Config):
        self.config = config
        self.last_wake = 0.0

    def wake(self) -> dict[str, object]:
        now = time.monotonic()
        if now - self.last_wake < 5:
            return {"accepted": True, "message": "wake recently sent"}
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(magic_packet(self.config.target_mac), (self.config.broadcast, 9))
        self.last_wake = now
        return {"accepted": True, "message": "magic packet sent"}

    def _tcp(self, port: int, timeout: float = 1.5) -> bool:
        try:
            with socket.create_connection((self.config.target_host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _ping(self) -> bool:
        try:
            result = subprocess.run(
                ["ping", "-c", "1", "-W", "1", self.config.target_host],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=3,
            )
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def _litellm(self) -> bool:
        request = urllib.request.Request(
            f"http://{self.config.target_host}:{self.config.litellm_port}/v1/models",
            headers={"Authorization": f"Bearer {self.config.litellm_key}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                data = json.load(response)
            return bool(data.get("data"))
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def _model(self) -> bool:
        body = json.dumps(
            {
                "model": "glm-4.7-flash",
                "messages": [{"role": "user", "content": "Reply with only OK"}],
                "max_tokens": 1,
                "stream": False,
            }
        ).encode()
        request = urllib.request.Request(
            f"http://{self.config.target_host}:{self.config.litellm_port}/v1/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.litellm_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.config.model_ready_timeout
            ) as response:
                data = json.load(response)
            return bool(data.get("choices"))
        except (OSError, ValueError, urllib.error.URLError):
            return False

    def status(self, probe_model: bool = False) -> dict[str, object]:
        ssh = self._tcp(22)
        litellm = self._litellm()
        reachable = ssh or litellm or self._ping()
        model_ready = bool(litellm and probe_model and self._model())
        if model_ready:
            state = "model-ready"
        elif litellm:
            state = "litellm-online"
        elif ssh:
            state = "host-online"
        elif reachable:
            state = "booting"
        else:
            state = "powered-off"
        return {
            "state": state,
            "host": self.config.target_host,
            "host_reachable": reachable,
            "ssh_online": ssh,
            "litellm_online": litellm,
            "model_ready": model_ready if probe_model else None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def shutdown(self) -> dict[str, object]:
        if not self.config.known_hosts.is_file() or not self.config.known_hosts.stat().st_size:
            raise RuntimeError("shutdown host key is not configured")
        command = [
            "ssh",
            "-T",
            "-i",
            str(self.config.ssh_key),
            "-o",
            "BatchMode=yes",
            "-o",
            "IdentitiesOnly=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            f"UserKnownHostsFile={self.config.known_hosts}",
            f"{self.config.ssh_user}@{self.config.target_host}",
            "request-safe-poweroff",
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout or "shutdown request failed").strip())
        return {"accepted": True, "message": "safe shutdown requested"}


PAGE = """<!doctype html><html><head><meta name=viewport content='width=device-width'>
<title>AI appliance power</title><style>body{font:18px system-ui;max-width:36rem;margin:3rem auto;padding:1rem;background:#111;color:#eee}button,input{font:inherit;padding:.8rem;margin:.35rem}button{cursor:pointer}.danger{color:#fff;background:#8b1e1e}pre{white-space:pre-wrap}</style></head>
<body><h1>AI appliance</h1><input id=t type=password placeholder='Relay token'><button onclick=save()>Save token</button><p id=s>Unknown</p><button onclick=callApi('wake')>Wake</button><button onclick=status()>Refresh</button><button class=danger onclick=shut()>Safe shutdown</button><pre id=o></pre>
<script>const t=document.querySelector('#t'),o=document.querySelector('#o'),s=document.querySelector('#s');t.value=localStorage.aiRelayToken||'';function save(){localStorage.aiRelayToken=t.value;status()}async function req(path,method='GET'){let r=await fetch('/v1/'+path,{method,headers:{Authorization:'Bearer '+t.value}}),j=await r.json();if(!r.ok)throw Error(j.error||r.status);return j}async function status(){try{let j=await req('status');s.textContent=j.state;o.textContent=JSON.stringify(j,null,2)}catch(e){o.textContent=e}}async function callApi(x){try{o.textContent=JSON.stringify(await req(x,'POST'),null,2);setTimeout(status,1500)}catch(e){o.textContent=e}}function shut(){if(confirm('Request safe shutdown?'))callApi('shutdown')}status()</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "AIPowerRelay/1"

    @property
    def relay(self) -> Relay:
        return self.server.relay  # type: ignore[attr-defined]

    def _json(self, status: int, value: object) -> None:
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authenticated(self) -> bool:
        supplied = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if hmac.compare_digest(supplied, self.relay.config.token):
            return True
        self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
        return False

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/":
            body = PAGE.encode()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif parsed.path == "/healthz":
            self._json(HTTPStatus.OK, {"status": "ok"})
        elif parsed.path == "/v1/status" and self._authenticated():
            probe = parse_qs(parsed.query).get("probe") == ["model"]
            self._json(HTTPStatus.OK, self.relay.status(probe_model=probe))
        elif parsed.path not in {"/v1/status"}:
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authenticated():
            return
        try:
            if self.path == "/v1/wake":
                value = self.relay.wake()
            elif self.path == "/v1/shutdown":
                value = self.relay.shutdown()
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
                return
            self._json(HTTPStatus.ACCEPTED, value)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            self._json(HTTPStatus.BAD_GATEWAY, {"error": html.escape(str(exc))[:500]})

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} {fmt % args}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    config = Config.from_env()
    if args.check:
        print("configuration valid")
        return 0
    server = ThreadingHTTPServer((config.listen_host, config.port), Handler)
    server.relay = Relay(config)  # type: ignore[attr-defined]
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
