from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from ai_appliance.manifest import ManifestError
from ai_appliance.queue import CommandResult, Queue, Runner, redact

ROOT = Path(__file__).resolve().parents[1]


class FailedRunner(Runner):
    def _worker(self, workspace, bundle, args, **kwargs):
        if args and args[0] == "run":
            result = CommandResult(7, False, 0.01, "simulated failure\n")
            if kwargs.get("log"):
                kwargs["log"].write(result.output)
            return result
        return CommandResult(0, False, 0.01, "")


class QueueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.jobs = root / "jobs"
        self.secrets = root / "secrets"
        self.deploy = root / "deploy"
        self.secrets.mkdir()
        self.deploy.mkdir()
        (self.secrets / "repositories.allow").write_text(
            "git@github.com:owner/repository.git\n", encoding="utf-8"
        )
        (self.secrets / "checks.allow").write_text("npm test*\n", encoding="utf-8")
        (self.deploy / ".env").write_text(
            "LITELLM_MASTER_KEY=super-secret-value\n", encoding="utf-8"
        )
        (self.deploy / "versions.env").write_text(
            "OPENCODE_VERSION=1.4.11\n", encoding="utf-8"
        )
        self.queue = Queue(self.jobs, self.secrets, self.deploy)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def fixture(self, name: str) -> Path:
        return ROOT / "tests/fixtures" / name

    def test_atomic_submit_claim_and_dry_run_success(self) -> None:
        self.assertEqual(self.queue.submit(self.fixture("success")), "fixture-success")
        claimed = self.queue.claim_next()
        self.assertIsNotNone(claimed)
        state = Runner(self.queue, dry_run=True).run(claimed)
        self.assertEqual(state, "completed")
        terminal = self.jobs / "completed/fixture-success"
        for filename in (
            "report.md",
            "metadata.json",
            "agent.log",
            "agent-events.jsonl",
            "checks.log",
            "git-status.txt",
            "git-diff.patch",
            "changed-files.txt",
            "commit.txt",
            "push.log",
            "status",
        ):
            self.assertTrue((terminal / filename).is_file(), filename)
        metadata = json.loads((terminal / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["state"], "completed")
        self.assertEqual(metadata["agent_version"], "1.4.11")

    def test_failed_fixture_moves_atomically(self) -> None:
        self.queue.submit(self.fixture("failed"))
        state = FailedRunner(self.queue).run(self.queue.claim_next())
        self.assertEqual(state, "failed")
        metadata = json.loads(
            (self.jobs / "failed/fixture-failed/metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["failure_category"], "agent")

    def test_cancelled_fixture(self) -> None:
        self.queue.submit(self.fixture("cancelled"))
        self.assertEqual(self.queue.cancel("fixture-cancelled"), "cancelled")
        self.assertTrue((self.jobs / "cancelled/fixture-cancelled").is_dir())

    def test_duplicate_and_path_traversal_are_rejected(self) -> None:
        self.queue.submit(self.fixture("success"))
        with self.assertRaises(ManifestError):
            self.queue.submit(self.fixture("success"))
        with self.assertRaises(ManifestError):
            self.queue.cancel("../../escape")

    def test_bundle_symlinks_are_rejected(self) -> None:
        bundle = Path(self.temp.name) / "bundle"
        shutil.copytree(self.fixture("success"), bundle)
        (bundle / "context").mkdir()
        (bundle / "context/escape").symlink_to("/etc/passwd")
        with self.assertRaisesRegex(ManifestError, "symlinks"):
            self.queue.submit(bundle)

    def test_command_has_only_narrow_explicit_job_mounts(self) -> None:
        runner = Runner(self.queue, dry_run=True)
        command = runner._compose_command(
            self.jobs / "workspaces/job", self.jobs / "running/job", ["version"]
        )
        rendered = " ".join(command)
        self.assertNotIn("/var/run/docker.sock", rendered)
        self.assertNotIn("/home/", rendered)
        self.assertIn(":/workspace:rw", rendered)
        self.assertIn(":/job:ro", rendered)

    def test_offline_jobs_use_isolated_network_but_git_control_plane_is_online(self) -> None:
        runner = Runner(self.queue, dry_run=True)
        runner.internet_access = False
        offline = runner._compose_command(
            self.jobs / "workspaces/job", self.jobs / "running/job", ["run", "model", "/job/task"]
        )
        git = runner._compose_command(
            self.jobs / "workspaces/job", self.jobs / "running/job", ["git", "clone", "url"]
        )
        self.assertIn("opencode-worker-offline", offline)
        self.assertNotIn("opencode-worker-offline", git)

    def test_secret_redaction(self) -> None:
        text = "Authorization: Bearer abcdefghi and token abcdefghi"
        safe = redact(text, ["abcdefghi"])
        self.assertNotIn("abcdefghi", safe)
        self.assertGreaterEqual(safe.count("[REDACTED]"), 2)


if __name__ == "__main__":
    unittest.main()
