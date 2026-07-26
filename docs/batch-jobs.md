# Batch coding jobs

Open WebUI is the user chat interface. OpenCode is the coding worker: normally
queued and unattended, with an explicit narrow-mount launcher for interactive
sessions. The interfaces remain deliberately separate.

## Interactive OpenCode

The same pinned worker can be used interactively without remembering its
Compose invocation:

```bash
cd ~/src/my-project
ai-opencode .
```

Choose a registered model for this session:

```bash
ai-opencode --model qwen-coder .
```

The launcher resolves the selected directory and mounts only that directory at
`/workspace`. It does not mount the host home, Docker socket, `/etc`, or
unrelated repositories. Put OpenCode-specific arguments after `--`:

```bash
ai-opencode . -- --help
```

Docker access follows the administrator account's normal Docker group policy.
If Docker requires elevation, use `sudo ai-opencode .`. The launcher passes the
original account's numeric UID/GID into the interactive container, so generated
files remain owned by that account rather than root.

## Queue and policies

The queue root is `/srv/ai-jobs`, with `queue`, `running`, `completed`, `failed`,
`cancelled`, `workspaces`, and `shared-cache`. Submission copies a validated
bundle to a hidden staging directory and atomically renames it into `queue`.
Claiming atomically renames one lexicographically sorted job into `running`.

Before submission, configure:

```text
/etc/ai-appliance/repositories.allow  exact URLs or narrow shell globs
/etc/ai-appliance/checks.allow        trusted full-command shell globs
/etc/ai-appliance/known_hosts         verified SSH host keys
/etc/ai-appliance/git_deploy_key      repository-scoped key
```

An allow-listed check still executes repository-controlled package scripts and
is untrusted code.

## Manifest

Start from `examples/batch-job`. The checked-in JSON Schema is
`schemas/job.schema.json`. The dependency-free loader supports the documented
mapping/scalar-list YAML subset and rejects aliases, tags, merges, duplicate
keys, control characters, newline injection, unsafe IDs/branches, credentialed
URLs, symlinks, and check shell metacharacters.

Commit policies:

- `never`: leave changes uncommitted;
- `always`: commit even if configured checks fail, but the job still ends failed;
- `tests-pass`: commit only when every configured check passes.

`push: true` pushes only `HEAD:refs/heads/<work_branch>`, without force. It never
pushes the base branch and never merges. A failed required push fails the job
and blocks success-only shutdown.

`internet_access: false` runs OpenCode and checks on an internal Docker network
that can reach LiteLLM but has no external route. The Git clone/push control
plane remains online because remote Git is required; package installs and web
fetches inside the task are blocked.

Only names in `environment.allow` are copied from the dispatcher environment.
No values are stored in the manifest. Do not use it for general credentials.

## Run and cancel

```bash
sudo scripts/submit-job ./job-directory
scripts/list-jobs
sudo scripts/run-next-job
sudo scripts/cancel-job unique-job-id
```

The systemd path unit normally invokes the runner automatically. Only one
oneshot service instance runs at a time. A running cancellation creates a marker;
the runner polls it while subprocesses execute, terminates the active process
group, flushes artifacts, and moves the job to `cancelled`.

Use a GPU-free dry run to validate orchestration without cloning or invoking
OpenCode:

```bash
sudo scripts/run-next-job --dry-run
```

## Artifacts

Every terminal job contains:

```text
report.md              metadata.json
agent.log              agent-events.jsonl
checks.log             git-status.txt
git-diff.patch         changed-files.txt
commit.txt             push.log
status
```

Metadata includes timestamps/duration, runner/model/agent, repository/branches,
commit and push state, check results, exit codes, shutdown decision, failure
category, and token/cost fields when available. The pinned OpenCode CLI runs
with `--format json`; valid JSON event lines are preserved and timestamped, while
non-JSON diagnostic lines are wrapped as output events. Token/cost remain null
when the upstream stream does not provide them.
