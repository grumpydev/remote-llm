"""Dependency-free parsing and strict validation for the supported job YAML subset."""
from __future__ import annotations

import fnmatch
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ENV_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
SHELL_META_RE = re.compile(r"[;&|`$<>\n\r]")


class ManifestError(ValueError):
    pass


def _scalar(text: str) -> Any:
    value = text.strip()
    if not value:
        return {}
    if value in {"true", "false"}:
        return value == "true"
    if value in {"null", "~"}:
        return None
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    if value.startswith("[") or value.startswith("{") or value.startswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"invalid JSON-style scalar: {value}") from exc
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1].replace("''", "'")
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def parse_yaml(text: str) -> dict[str, Any]:
    """Parse mappings and scalar sequences used by the manifest schema.

    JSON is accepted directly because it is a YAML subset. YAML aliases, tags,
    block scalars, merge keys, and sequence mappings are intentionally rejected.
    """
    if len(text.encode("utf-8")) > 128 * 1024:
        raise ManifestError("manifest exceeds 128 KiB")
    try:
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ManifestError("manifest root must be a mapping")
        return parsed
    except json.JSONDecodeError:
        pass

    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw:
            raise ManifestError(f"line {number}: tabs are not allowed")
        indent = len(raw) - len(raw.lstrip(" "))
        if indent % 2:
            raise ManifestError(f"line {number}: indentation must use two spaces")
        stripped = raw.strip()
        if any(token in stripped for token in ("&", "*", "!!", "<<:")):
            raise ManifestError(f"line {number}: advanced YAML features are disabled")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ManifestError(f"line {number}: invalid indentation")
        parent = stack[-1][1]
        if stripped.startswith("- "):
            if not isinstance(parent, list):
                raise ManifestError(f"line {number}: sequence has no list parent")
            parent.append(_scalar(stripped[2:]))
            continue
        key, sep, value = stripped.partition(":")
        if not sep or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ManifestError(f"line {number}: invalid mapping entry")
        if not isinstance(parent, dict) or key in parent:
            raise ManifestError(f"line {number}: duplicate key or invalid parent")
        if value.strip():
            parent[key] = _scalar(value)
            continue
        # Decide whether the child is a list by peeking at the next meaningful line.
        following = text.splitlines()[number:]
        child: Any = {}
        for candidate in following:
            if not candidate.strip() or candidate.lstrip().startswith("#"):
                continue
            next_indent = len(candidate) - len(candidate.lstrip(" "))
            if next_indent > indent and candidate.strip().startswith("- "):
                child = []
            break
        parent[key] = child
        stack.append((indent, child))
    return root


def _exact_keys(value: dict[str, Any], allowed: set[str], where: str) -> None:
    extra = set(value) - allowed
    if extra:
        raise ManifestError(f"{where}: unknown keys: {', '.join(sorted(extra))}")


def safe_branch(value: Any, field: str) -> str:
    if not isinstance(value, str) or not BRANCH_RE.fullmatch(value):
        raise ManifestError(f"{field}: unsafe branch")
    if value.startswith(("-", ".")) or value.endswith(("/", ".", ".lock")):
        raise ManifestError(f"{field}: unsafe branch")
    if ".." in value or "@{" in value or "//" in value:
        raise ManifestError(f"{field}: unsafe branch")
    return value


def load_patterns(path: Path) -> list[str]:
    if not path.is_file():
        raise ManifestError(f"policy file missing: {path}")
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def validate_repository(url: Any, patterns: list[str]) -> str:
    if not isinstance(url, str) or len(url) > 512 or CONTROL_RE.search(url):
        raise ManifestError("repository.url: invalid")
    if url.startswith("git@"):
        if not re.fullmatch(r"git@[A-Za-z0-9.-]+:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", url):
            raise ManifestError("repository.url: unsafe SSH URL")
    else:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ManifestError("repository.url: only strict SSH or HTTPS URLs are allowed")
    if not any(fnmatch.fnmatchcase(url, pattern) for pattern in patterns):
        raise ManifestError("repository.url: not in repositories.allow")
    return url


def validate_check(command: Any, patterns: list[str]) -> str:
    if not isinstance(command, str) or not 1 <= len(command) <= 512:
        raise ManifestError("check command has invalid length")
    if CONTROL_RE.search(command) or SHELL_META_RE.search(command):
        raise ManifestError(f"check command contains shell metacharacters: {command!r}")
    try:
        words = shlex.split(command)
    except ValueError as exc:
        raise ManifestError(f"invalid check command: {command!r}") from exc
    if not words or words[0].startswith(("/", ".")):
        raise ManifestError(f"unsafe check executable: {command!r}")
    if not any(fnmatch.fnmatchcase(command, pattern) for pattern in patterns):
        raise ManifestError(f"check not allowed by checks.allow: {command!r}")
    return command


@dataclass(frozen=True)
class Job:
    raw: dict[str, Any]
    id: str
    repository_url: str
    base_branch: str
    work_branch: str
    task_file: str
    model: str
    max_runtime_minutes: int
    internet_access: bool
    commit_policy: str
    push: bool
    shutdown_on_success: bool
    shutdown_on_failure: bool
    shutdown_delay_seconds: int
    checks: tuple[str, ...]
    environment_allow: tuple[str, ...]


def validate_manifest(
    value: dict[str, Any], repositories_allow: Path, checks_allow: Path
) -> Job:
    _exact_keys(
        value,
        {"version", "id", "repository", "task_file", "model", "agent", "execution", "checks", "environment"},
        "manifest",
    )
    if value.get("version") != 1:
        raise ManifestError("version must be 1")
    job_id = value.get("id")
    if not isinstance(job_id, str) or not ID_RE.fullmatch(job_id):
        raise ManifestError("id must match ^[a-z0-9][a-z0-9-]{0,62}$")
    if value.get("agent") != "opencode":
        raise ManifestError("agent must be opencode")
    task_file = value.get("task_file")
    if not isinstance(task_file, str) or not FILE_RE.fullmatch(task_file):
        raise ManifestError("task_file is unsafe")
    model = value.get("model")
    if not isinstance(model, str) or not NAME_RE.fullmatch(model):
        raise ManifestError("model is unsafe")

    repo = value.get("repository")
    if not isinstance(repo, dict):
        raise ManifestError("repository must be a mapping")
    _exact_keys(repo, {"url", "base_branch", "work_branch"}, "repository")
    repository_url = validate_repository(repo.get("url"), load_patterns(repositories_allow))
    base_branch = safe_branch(repo.get("base_branch"), "repository.base_branch")
    work_branch = safe_branch(repo.get("work_branch"), "repository.work_branch")
    if base_branch == work_branch:
        raise ManifestError("work branch must differ from base branch")

    execution = value.get("execution")
    if not isinstance(execution, dict):
        raise ManifestError("execution must be a mapping")
    _exact_keys(
        execution,
        {
            "max_runtime_minutes",
            "internet_access",
            "commit_policy",
            "push",
            "shutdown_on_success",
            "shutdown_on_failure",
            "shutdown_delay_seconds",
        },
        "execution",
    )
    runtime = execution.get("max_runtime_minutes")
    if not isinstance(runtime, int) or isinstance(runtime, bool) or not 5 <= runtime <= 720:
        raise ManifestError("max_runtime_minutes must be 5..720")
    internet = execution.get("internet_access")
    push = execution.get("push")
    if not isinstance(internet, bool) or not isinstance(push, bool):
        raise ManifestError("internet_access and push must be booleans")
    policy = execution.get("commit_policy")
    if policy not in {"never", "always", "tests-pass"}:
        raise ManifestError("invalid commit_policy")
    delay = execution.get("shutdown_delay_seconds", 60)
    if not isinstance(delay, int) or isinstance(delay, bool) or not 30 <= delay <= 3600:
        raise ManifestError("shutdown_delay_seconds must be 30..3600")
    on_success = execution.get("shutdown_on_success", False)
    on_failure = execution.get("shutdown_on_failure", False)
    if not isinstance(on_success, bool) or not isinstance(on_failure, bool):
        raise ManifestError("shutdown flags must be booleans")

    check_values = value.get("checks", [])
    if not isinstance(check_values, list) or len(check_values) > 20:
        raise ManifestError("checks must be a list of at most 20 commands")
    check_patterns = load_patterns(checks_allow)
    checks = tuple(validate_check(item, check_patterns) for item in check_values)

    environment = value.get("environment", {})
    if not isinstance(environment, dict):
        raise ManifestError("environment must be a mapping")
    _exact_keys(environment, {"allow"}, "environment")
    env_allow = environment.get("allow", [])
    if not isinstance(env_allow, list) or len(env_allow) > 32:
        raise ManifestError("environment.allow must be a list")
    if any(not isinstance(item, str) or not ENV_RE.fullmatch(item) for item in env_allow):
        raise ManifestError("environment.allow contains an unsafe name")

    return Job(
        raw=value,
        id=job_id,
        repository_url=repository_url,
        base_branch=base_branch,
        work_branch=work_branch,
        task_file=task_file,
        model=model,
        max_runtime_minutes=runtime,
        internet_access=internet,
        commit_policy=policy,
        push=push,
        shutdown_on_success=on_success,
        shutdown_on_failure=on_failure,
        shutdown_delay_seconds=delay,
        checks=checks,
        environment_allow=tuple(env_allow),
    )


def load_job(path: Path, repositories_allow: Path, checks_allow: Path) -> Job:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ManifestError("manifest must be UTF-8") from exc
    return validate_manifest(parse_yaml(text), repositories_allow, checks_allow)

