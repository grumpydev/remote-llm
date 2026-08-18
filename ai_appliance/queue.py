"""Filesystem queue and isolated worker orchestration."""
from __future__ import annotations

import hashlib
import json
import os
import selectors
import shutil
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Iterable

from . import __version__
from .manifest import ID_RE, Job, ManifestError, load_job

STATES = ("queue", "running", "completed", "failed", "cancelled")
OUTPUTS = (
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
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(text: str, secrets: Iterable[str]) -> str:
    result = text
    for secret in sorted((item for item in secrets if len(item) >= 6), key=len, reverse=True):
        result = result.replace(secret, "[REDACTED]")
    result = result.replace("Authorization: Bearer ", "Authorization: Bearer [REDACTED]")
    return result


@dataclass
class CommandResult:
    returncode: int
    timed_out: bool
    duration_seconds: float
    output: str


class Queue:
    def __init__(self, root: Path, secrets_dir: Path, deploy_dir: Path):
        self.root = root
        self.secrets_dir = secrets_dir
        self.deploy_dir = deploy_dir

    def initialise(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for name in (*STATES, "workspaces", "shared-cache"):
            (self.root / name).mkdir(mode=0o750, exist_ok=True)

    def locate(self, job_id: str) -> tuple[str, Path] | None:
        if not ID_RE.fullmatch(job_id):
            raise ManifestError("unsafe job ID")
        for state in STATES:
            path = self.root / state / job_id
            if path.is_dir():
                return state, path
        return None

    def submit(self, source: Path) -> str:
        self.initialise()
        if not source.is_dir():
            raise ManifestError(f"job bundle not found: {source}")
        job = load_job(
            source / "job.yaml",
            self.secrets_dir / "repositories.allow",
            self.secrets_dir / "checks.allow",
        )
        task = (source / job.task_file).resolve()
        if task.parent != source.resolve() or not task.is_file():
            raise ManifestError("task file missing or outside bundle")
        if task.stat().st_size > 1024 * 1024:
            raise ManifestError("task file exceeds 1 MiB")
        if self.locate(job.id):
            raise ManifestError(f"job already exists: {job.id}")
        for item in source.rglob("*"):
            if item.is_symlink():
                raise ManifestError("symlinks are not allowed in job bundles")
        staging = self.root / "queue" / f".{job.id}.{os.getpid()}.tmp"
        shutil.copytree(source, staging, symlinks=False)
        os.replace(staging, self.root / "queue" / job.id)
        return job.id

    def claim_next(self) -> Path | None:
        self.initialise()
        for candidate in sorted((self.root / "queue").iterdir()):
            if candidate.name.startswith(".") or not candidate.is_dir():
                continue
            target = self.root / "running" / candidate.name
            try:
                os.replace(candidate, target)
                return target
            except (FileNotFoundError, FileExistsError):
                continue
        return None

    def cancel(self, job_id: str) -> str:
        located = self.locate(job_id)
        if not located:
            raise ManifestError(f"job not found: {job_id}")
        state, path = located
        if state == "queue":
            (path / "cancel.requested").write_text(utc_now() + "\n", encoding="utf-8")
            os.replace(path, self.root / "cancelled" / job_id)
            (self.root / "cancelled" / job_id / "status").write_text("cancelled\n", encoding="utf-8")
            return "cancelled"
        if state == "running":
            (path / "cancel.requested").write_text(utc_now() + "\n", encoding="utf-8")
            return "cancellation-requested"
        return state


class Runner:
    def __init__(self, queue: Queue, dry_run: bool = False):
        self.queue = queue
        self.dry_run = dry_run
        self.started = time.monotonic()
        self.deadline = float("inf")
        self.secrets = self._secret_values()
        self.allowed_environment: tuple[str, ...] = ()
        self.current_bundle: Path | None = None
        self.internet_access = True

    def _secret_values(self) -> list[str]:
        values: list[str] = []
        env_file = self.queue.deploy_dir / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    values.append(line.split("=", 1)[1])
        return values

    def _locked_opencode_version(self) -> str | None:
        path = self.queue.deploy_dir / "versions.env"
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENCODE_VERSION="):
                    return line.split("=", 1)[1]
        return None

    def _remaining(self) -> float:
        return max(1.0, self.deadline - time.monotonic())

    def _compose_command(self, workspace: Path, bundle: Path, args: list[str]) -> list[str]:
        command = [
            "docker",
            "compose",
            "--project-directory",
            str(self.queue.deploy_dir),
            "--env-file",
            str(self.queue.deploy_dir / "versions.env"),
            "--env-file",
            str(self.queue.deploy_dir / ".env"),
            "-f",
            str(self.queue.deploy_dir / "compose.yaml"),
            "-f",
            str(self.queue.deploy_dir / "compose.worker.yaml"),
            "--profile",
            "worker",
            "run",
            "--rm",
        ]
        for name in self.allowed_environment:
            if name in os.environ:
                command.extend(["-e", name])
        service = (
            "opencode-worker"
            if self.internet_access or (args and args[0] == "git")
            else "opencode-worker-offline"
        )
        command.extend(
            [
                "-v",
                f"{workspace}:/workspace:rw",
                "-v",
                f"{bundle}:/job:ro",
                service,
                *args,
            ]
        )
        return command

    def _run(
        self,
        command: list[str],
        log: IO[str] | None = None,
        events: IO[str] | None = None,
        timeout: float | None = None,
        cwd: Path | None = None,
    ) -> CommandResult:
        started = time.monotonic()
        if self.dry_run:
            output = "DRY RUN: " + " ".join(command) + "\n"
            if log:
                log.write(output)
            return CommandResult(0, False, 0.0, output)
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            start_new_session=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        output: list[str] = []
        limit = min(timeout or self._remaining(), self._remaining())
        timed_out = False
        assert process.stdout is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        while process.poll() is None:
            cancelled = bool(
                self.current_bundle and self.current_bundle.joinpath("cancel.requested").exists()
            )
            if cancelled or time.monotonic() - started > limit:
                timed_out = True
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                break
            for key, _ in selector.select(timeout=0.25):
                line = key.fileobj.readline()
                if not line:
                    continue
                safe = redact(line, self.secrets)
                output.append(safe)
                if log:
                    log.write(safe)
                    log.flush()
                if events:
                    try:
                        event = json.loads(safe)
                        if not isinstance(event, dict):
                            raise ValueError
                        event.setdefault("captured_at", utc_now())
                    except (json.JSONDecodeError, ValueError):
                        event = {"captured_at": utc_now(), "type": "output", "text": safe}
                    events.write(json.dumps(event, sort_keys=True) + "\n")
                    events.flush()
        remainder = process.stdout.read()
        if remainder:
            safe = redact(remainder, self.secrets)
            output.append(safe)
            if log:
                log.write(safe)
        return CommandResult(
            124 if timed_out else int(process.returncode or 0),
            timed_out,
            time.monotonic() - started,
            "".join(output),
        )

    def _worker(self, workspace: Path, bundle: Path, args: list[str], **kwargs: Any) -> CommandResult:
        return self._run(self._compose_command(workspace, bundle, args), **kwargs)

    def _write_capture(self, path: Path, result: CommandResult) -> None:
        path.write_text(result.output, encoding="utf-8")

    def run(self, bundle: Path) -> str:
        started_at = utc_now()
        metadata: dict[str, Any] = {
            "runner_version": __version__,
            "agent_version": self._locked_opencode_version(),
            "started_at": started_at,
            "job_id": bundle.name,
            "dry_run": self.dry_run,
            "failure_category": None,
            "exit_codes": {},
            "checks": [],
            "push": {"requested": False, "succeeded": False},
            "shutdown": {"requested": False, "scheduled": False},
            "token_usage": None,
            "cost": None,
        }
        workspace = self.queue.root / "workspaces" / bundle.name
        final_state = "failed"
        failure = ""
        job: Job | None = None
        try:
            job = load_job(
                bundle / "job.yaml",
                self.queue.secrets_dir / "repositories.allow",
                self.queue.secrets_dir / "checks.allow",
            )
            if job.id != bundle.name:
                raise ManifestError("claimed directory does not match manifest id")
            self.current_bundle = bundle
            self.deadline = time.monotonic() + job.max_runtime_minutes * 60
            self.allowed_environment = job.environment_allow
            self.internet_access = job.internet_access
            self.secrets.extend(
                os.environ[name] for name in job.environment_allow if name in os.environ
            )
            metadata.update(
                {
                    "model": job.model,
                    "agent": "opencode",
                    "repository": job.repository_url,
                    "base_branch": job.base_branch,
                    "work_branch": job.work_branch,
                    "commit_policy": job.commit_policy,
                    "push": {"requested": job.push, "succeeded": False},
                }
            )
            if bundle.joinpath("cancel.requested").exists():
                final_state = "cancelled"
                raise InterruptedError("cancelled before start")
            if workspace.exists():
                raise ManifestError(f"workspace already exists: {workspace}")
            workspace.mkdir(parents=True, mode=0o750)
            if os.geteuid() == 0:
                os.chown(workspace, 1000, 1000)

            git_log = bundle / "git-prepare.log"
            with git_log.open("w", encoding="utf-8") as handle:
                clone = self._worker(
                    workspace,
                    bundle,
                    ["git", "clone", "--no-tags", "--single-branch", "--branch", job.base_branch, job.repository_url, "."],
                    log=handle,
                )
                metadata["exit_codes"]["clone"] = clone.returncode
                if clone.returncode:
                    metadata["failure_category"] = "clone"
                    raise RuntimeError("repository clone failed")
                branch = self._worker(
                    workspace, bundle, ["git", "checkout", "-b", job.work_branch], log=handle
                )
                metadata["exit_codes"]["checkout"] = branch.returncode
                if branch.returncode:
                    metadata["failure_category"] = "checkout"
                    raise RuntimeError("work branch creation failed")

            context = bundle / "context"
            if context.is_dir():
                shutil.copytree(context, workspace / ".ai-job-context", symlinks=False)
            task = (bundle / job.task_file).read_text(encoding="utf-8")
            instruction = (
                "# Bounded batch coding task\n\n"
                f"Repository: {job.repository_url}\nBase branch: {job.base_branch}\n"
                f"Work branch: {job.work_branch}\n\n"
                "Work only inside /workspace. Do not commit, push, alter remotes, access "
                "external directories, or request user input. Implement the task, inspect "
                "your changes, and leave the workspace ready for configured checks. "
                f"The host enforces a {job.max_runtime_minutes}-minute total deadline.\n\n"
                "## Task\n\n" + task
            )
            (bundle / "instruction.md").write_text(instruction, encoding="utf-8")
            with (bundle / "agent.log").open("w", encoding="utf-8") as log, (
                bundle / "agent-events.jsonl"
            ).open("w", encoding="utf-8") as events:
                result = self._worker(
                    workspace,
                    bundle,
                    ["run", job.model, "/job/instruction.md"],
                    log=log,
                    events=events,
                )
            metadata["exit_codes"]["agent"] = result.returncode
            metadata["agent_duration_seconds"] = round(result.duration_seconds, 3)
            if bundle.joinpath("cancel.requested").exists():
                final_state = "cancelled"
                raise InterruptedError("cancellation requested")
            if result.timed_out:
                metadata["failure_category"] = "timeout"
                raise TimeoutError("agent exceeded job deadline")
            if result.returncode:
                metadata["failure_category"] = "agent"
                raise RuntimeError("OpenCode returned non-zero")
            if bundle.joinpath("cancel.requested").exists():
                final_state = "cancelled"
                raise InterruptedError("cancellation requested")

            checks_ok = True
            with (bundle / "checks.log").open("w", encoding="utf-8") as checks_log:
                for command in job.checks:
                    check = self._worker(
                        workspace, bundle, ["shell", "/bin/sh", "-lc", command], log=checks_log
                    )
                    item = {
                        "command": command,
                        "exit_code": check.returncode,
                        "duration_seconds": round(check.duration_seconds, 3),
                    }
                    metadata["checks"].append(item)
                    checks_ok = checks_ok and check.returncode == 0
                    if bundle.joinpath("cancel.requested").exists():
                        final_state = "cancelled"
                        raise InterruptedError("cancellation requested")
            metadata["checks_passed"] = checks_ok

            captures = {
                "git-status.txt": ["git", "status", "--short", "--branch"],
                "git-diff.patch": ["git", "diff", "--binary", "--no-ext-diff"],
                "changed-files.txt": ["git", "diff", "--name-only", "HEAD"],
            }
            for filename, args in captures.items():
                self._write_capture(bundle / filename, self._worker(workspace, bundle, args))

            should_commit = job.commit_policy == "always" or (
                job.commit_policy == "tests-pass" and checks_ok
            )
            commit_sha = ""
            if should_commit:
                self._worker(workspace, bundle, ["git", "add", "-A"])
                commit = self._worker(
                    workspace,
                    bundle,
                    ["git", "-c", "user.name=AI Appliance", "-c", "user.email=ai-appliance@localhost", "commit", "-m", f"agent: {job.id}"],
                )
                metadata["exit_codes"]["commit"] = commit.returncode
                if commit.returncode and "nothing to commit" not in commit.output:
                    metadata["failure_category"] = "commit"
                    raise RuntimeError("commit failed")
                sha = self._worker(workspace, bundle, ["git", "rev-parse", "HEAD"])
                commit_sha = sha.output.strip()
            (bundle / "commit.txt").write_text(commit_sha + ("\n" if commit_sha else ""), encoding="utf-8")
            metadata["commit_sha"] = commit_sha or None

            push_ok = not job.push
            if job.push:
                if not should_commit or not commit_sha:
                    push = CommandResult(2, False, 0, "Push skipped: no policy-approved commit.\n")
                else:
                    push = self._worker(
                        workspace,
                        bundle,
                        ["git", "push", "origin", f"HEAD:refs/heads/{job.work_branch}"],
                    )
                self._write_capture(bundle / "push.log", push)
                metadata["exit_codes"]["push"] = push.returncode
                push_ok = push.returncode == 0
                metadata["push"]["succeeded"] = push_ok
            else:
                (bundle / "push.log").write_text("Push not requested.\n", encoding="utf-8")

            if not checks_ok:
                metadata["failure_category"] = "checks"
                raise RuntimeError("one or more configured checks failed")
            if job.push and not push_ok:
                metadata["failure_category"] = "push"
                raise RuntimeError("required branch push failed")
            final_state = "completed"
        except InterruptedError as exc:
            final_state = "cancelled"
            metadata["failure_category"] = "cancelled"
            failure = str(exc)
        except (ManifestError, UnicodeDecodeError) as exc:
            metadata["failure_category"] = "validation"
            failure = str(exc)
        except Exception as exc:  # failure is fully reported before terminal transition
            failure = str(exc)
            if not metadata["failure_category"]:
                metadata["failure_category"] = "runner"
        finally:
            for name in OUTPUTS:
                path = bundle / name
                if not path.exists():
                    path.write_text("" if name != "status" else final_state + "\n", encoding="utf-8")
            success = final_state == "completed"
            shutdown_requested = bool(
                job
                and (
                    (success and job.shutdown_on_success)
                    or (not success and job.shutdown_on_failure)
                )
            )
            if job and success and job.push and not metadata["push"]["succeeded"]:
                shutdown_requested = False
            metadata["shutdown"]["requested"] = shutdown_requested
            if shutdown_requested and not self.dry_run:
                request = self.queue.root / "shutdown.request"
                request.write_text(
                    json.dumps(
                        {
                            "version": 1,
                            "source": "batch",
                            "job_id": bundle.name,
                            "not_before_epoch": int(time.time()) + job.shutdown_delay_seconds,
                            "state": final_state,
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                metadata["shutdown"]["scheduled"] = True
            metadata["finished_at"] = utc_now()
            metadata["duration_seconds"] = round(time.monotonic() - self.started, 3)
            metadata["state"] = final_state
            metadata["error"] = redact(failure, self.secrets) or None
            (bundle / "metadata.json").write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            (bundle / "status").write_text(final_state + "\n", encoding="utf-8")
            report = (
                f"# Job {bundle.name}\n\n"
                f"- Status: `{final_state}`\n"
                f"- Started: {started_at}\n"
                f"- Finished: {metadata['finished_at']}\n"
                f"- Repository: `{metadata.get('repository', 'unknown')}`\n"
                f"- Branch: `{metadata.get('work_branch', 'unknown')}`\n"
                f"- Commit: `{metadata.get('commit_sha') or 'none'}`\n"
                f"- Push succeeded: `{metadata['push']['succeeded']}`\n"
                f"- Failure category: `{metadata.get('failure_category') or 'none'}`\n"
                f"- Error: {metadata['error'] or 'none'}\n"
            )
            (bundle / "report.md").write_text(report, encoding="utf-8")
            target = self.queue.root / final_state / bundle.name
            if target.exists():
                raise RuntimeError(f"terminal job path already exists: {target}")
            os.replace(bundle, target)
        return final_state
