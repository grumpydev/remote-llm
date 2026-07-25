#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC2034 # shared by scripts that source this library
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DEPLOY_DIR="${AI_APPLIANCE_DIR:-/opt/ai-appliance}"
# shellcheck disable=SC2034 # shared by scripts that source this library
BACKUP_ROOT="${AI_BACKUP_DIR:-/var/backups/ai-appliance}"
# shellcheck disable=SC2034 # shared by scripts that source this library
SECRETS_DIR="${AI_SECRETS_DIR:-/etc/ai-appliance}"

die() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 1
}

log() {
	printf '%s\n' "$*"
}

require_root() {
	[[ "${EUID}" -eq 0 ]] || die "run with sudo"
}

require_command() {
	command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

compose() {
	docker compose --project-directory "${DEPLOY_DIR}" \
		--env-file "${DEPLOY_DIR}/versions.env" \
		--env-file "${DEPLOY_DIR}/.env" "$@"
}

worker_compose() {
	docker compose --project-directory "${DEPLOY_DIR}" \
		--env-file "${DEPLOY_DIR}/versions.env" \
		--env-file "${DEPLOY_DIR}/.env" \
		-f "${DEPLOY_DIR}/compose.yaml" \
		-f "${DEPLOY_DIR}/compose.worker.yaml" "$@"
}

detect_tailscale_ip() {
	require_command tailscale
	local ip
	ip="$(tailscale ip -4 2>/dev/null | head -n1)"
	[[ "${ip}" =~ ^100\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]] ||
		die "could not detect a Tailscale IPv4 address; check 'tailscale status'"
	printf '%s\n' "${ip}"
}

random_secret() {
	require_command openssl
	openssl rand -hex 32
}

atomic_write() {
	local target="$1"
	local mode="$2"
	local tmp
	tmp="$(mktemp "${target}.XXXXXX")"
	cat >"${tmp}"
	chmod "${mode}" "${tmp}"
	mv -f -- "${tmp}" "${target}"
}

validate_deployment() {
	compose config --quiet
	compose ps --status running --services | grep -qx searxng ||
		die "SearXNG is not running"
	compose ps --status running --services | grep -qx litellm ||
		die "LiteLLM is not running"
	compose ps --status running --services | grep -qx open-webui ||
		die "Open WebUI is not running"
	"${DEPLOY_DIR}/scripts/doctor" --runtime-only
}
