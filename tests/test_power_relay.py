import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_appliance.power_relay import Config, Relay, magic_packet


class PowerRelayTests(unittest.TestCase):
    def test_magic_packet(self) -> None:
        packet = magic_packet("00:11:22:33:44:55")
        self.assertEqual(len(packet), 102)
        self.assertEqual(packet[:6], b"\xff" * 6)
        self.assertEqual(packet[6:12], bytes.fromhex("001122334455"))
        self.assertEqual(packet[-6:], bytes.fromhex("001122334455"))

    def test_configuration_uses_files_for_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            token = root / "token"
            key = root / "litellm"
            token.write_text("a" * 64, encoding="utf-8")
            key.write_text("sk-test", encoding="utf-8")
            environment = {
                "AI_RELAY_TOKEN_FILE": str(token),
                "AI_TARGET_LITELLM_KEY_FILE": str(key),
                "AI_RELAY_LISTEN_HOST": "100.64.0.2",
                "AI_RELAY_PORT": "8099",
                "AI_TARGET_MAC": "00:11:22:33:44:55",
                "AI_TARGET_HOST": "ai-server",
                "AI_RELAY_BROADCAST": "192.168.1.255",
                "AI_SHUTDOWN_SSH_KEY": str(root / "id"),
                "AI_SHUTDOWN_KNOWN_HOSTS": str(root / "known_hosts"),
            }
            with patch.dict(os.environ, environment, clear=True):
                config = Config.from_env()
            self.assertEqual(config.target_host, "ai-server")
            self.assertEqual(config.token, "a" * 64)
            self.assertEqual(config.target_mac, "00:11:22:33:44:55")
            self.assertEqual(config.ssh_port, 2222)

    def test_shutdown_uses_dedicated_openssh_port(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            known_hosts = root / "known_hosts"
            known_hosts.write_text("pinned\n", encoding="utf-8")
            config = Config(
                listen_host="100.64.0.2",
                port=8099,
                token="a" * 64,
                target_mac="00:11:22:33:44:55",
                target_host="ai-server",
                broadcast="192.168.1.255",
                litellm_port=4000,
                litellm_key="key",
                ssh_user="ai-power-relay",
                ssh_key=root / "id",
                known_hosts=known_hosts,
            )
            with patch("ai_appliance.power_relay.subprocess.run") as run:
                run.return_value.returncode = 0
                Relay(config).shutdown()
            command = run.call_args.args[0]
            self.assertEqual(command[command.index("-p") + 1], "2222")

    def test_rejects_unsafe_target_host(self) -> None:
        config = Config(
            listen_host="100.64.0.2",
            port=8099,
            token="a" * 64,
            target_mac="00:11:22:33:44:55",
            target_host="host;poweroff",
            broadcast="192.168.1.255",
            litellm_port=4000,
            litellm_key="key",
            ssh_user="ai-power-relay",
            ssh_key=Path("/key"),
            known_hosts=Path("/known"),
        )
        with self.assertRaises(ValueError):
            config.validate()


if __name__ == "__main__":
    unittest.main()
