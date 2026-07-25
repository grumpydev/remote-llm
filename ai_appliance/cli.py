"""Command line interface for filesystem jobs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .manifest import ManifestError
from .queue import Queue, Runner, STATES


def paths() -> tuple[Path, Path, Path]:
    return (
        Path(os.environ.get("AI_JOBS_ROOT", "/srv/ai-jobs")),
        Path(os.environ.get("AI_SECRETS_DIR", "/etc/ai-appliance")),
        Path(os.environ.get("AI_APPLIANCE_DIR", "/opt/ai-appliance")),
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="ai-job")
    result.add_argument("--root", type=Path)
    result.add_argument("--secrets-dir", type=Path)
    result.add_argument("--deploy-dir", type=Path)
    sub = result.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("bundle", type=Path)
    run = sub.add_parser("run-next")
    run.add_argument("--dry-run", action="store_true")
    sub.add_parser("list")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("job_id")
    validate = sub.add_parser("validate")
    validate.add_argument("bundle", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    default_root, default_secrets, default_deploy = paths()
    queue = Queue(
        args.root or default_root,
        args.secrets_dir or default_secrets,
        args.deploy_dir or default_deploy,
    )
    try:
        if args.command == "submit":
            print(queue.submit(args.bundle))
        elif args.command == "run-next":
            bundle = queue.claim_next()
            if not bundle:
                print("No queued jobs.")
                return 0
            state = Runner(queue, dry_run=args.dry_run).run(bundle)
            print(f"{bundle.name}: {state}")
            return 0 if state == "completed" else 1
        elif args.command == "list":
            queue.initialise()
            rows = []
            for state in STATES:
                for item in sorted((queue.root / state).iterdir()):
                    if item.is_dir() and not item.name.startswith("."):
                        rows.append({"id": item.name, "state": state})
            print(json.dumps(rows, indent=2))
        elif args.command == "cancel":
            print(queue.cancel(args.job_id))
        elif args.command == "validate":
            # Submit validation without mutating the queue.
            from .manifest import load_job

            job = load_job(
                args.bundle / "job.yaml",
                queue.secrets_dir / "repositories.allow",
                queue.secrets_dir / "checks.allow",
            )
            if not (args.bundle / job.task_file).is_file():
                raise ManifestError("task file missing")
            print(job.id)
        return 0
    except ManifestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

