# Implementation plan

## Constraints and decisions

- Keep NVIDIA, CUDA, Tailscale, llama.cpp, models, and host power control native.
- Run LiteLLM, Open WebUI, and SearXNG as a pinned Docker Compose application.
- Bind client ports to loopback and the dynamically discovered Tailscale IPv4.
- Preserve an existing Open WebUI volume and never remove data implicitly.
- Implement the batch system as a small dependency-light Python package behind
  shell entry points and a filesystem queue.
- Run each coding job in a disposable, capability-restricted OpenCode container.
- Treat repository code and its checks as untrusted. Docker reduces exposure but
  is not a security boundary equivalent to a virtual machine.
- Keep native llama.cpp lifecycle independent from appliance update/rollback.

## Phases

1. Document the architecture, trust boundaries, migration and rollback shape.
2. Add the pinned Compose stack, rendered LiteLLM/SearXNG configuration, secrets,
   binding, health checks, and version lock.
3. Add idempotent install, migration, backup/restore, update/rollback, model
   management, status, and doctor commands.
4. Build a pinned OpenCode worker with no inbound port, Docker socket, host home,
   or broad host filesystem access.
5. Add atomic queue claiming, schema validation, repository allow-listing,
   timeouts, cancellation, branch-only commit/push, complete artifacts, and safe
   shutdown scheduling.
6. Add unit, fixture, schema, Compose, shell, and GPU-free smoke tests.
7. Complete operator documentation; deployment-specific build reports are
   generated locally and ignored by Git.

## Validation gates

- Python unit tests and compilation after each queue/runner phase.
- Shell syntax and ShellCheck; formatting checks when the tools are installed.
- JSON/YAML parsing and JSON Schema fixture validation.
- `docker compose config` when Docker Compose is available.
- Dry-run install/migrate/update/worker flows without an NVIDIA GPU.
- No phase reports success until its required checks have completed.

## Commit boundaries

Each independently usable phase is committed separately: architecture, core
stack, lifecycle tooling, diagnostics/model management, worker image, queue
runner, policy/reporting, tests, then operator documentation.
