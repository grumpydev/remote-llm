#!/bin/sh
set -eu

die() {
	printf 'ERROR: %s\n' "$*" >&2
	exit 2
}

setup_git_credentials() {
	mkdir -p "${HOME}/.ssh"
	chmod 700 "${HOME}/.ssh"
	if [ -s /run/secrets/known_hosts ]; then
		cp /run/secrets/known_hosts "${HOME}/.ssh/known_hosts"
		chmod 600 "${HOME}/.ssh/known_hosts"
	fi
	if [ -s /run/secrets/git_deploy_key ]; then
		cp /run/secrets/git_deploy_key "${HOME}/.ssh/id_ed25519"
		chmod 600 "${HOME}/.ssh/id_ed25519"
		export GIT_SSH_COMMAND="ssh -i ${HOME}/.ssh/id_ed25519 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=${HOME}/.ssh/known_hosts"
	fi
}

case "${1:-help}" in
version)
	opencode --version
	git --version
	;;
git)
	shift
	setup_git_credentials
	exec git "$@"
	;;
run)
	shift
	[ $# -eq 2 ] || die "usage: worker-entrypoint run MODEL INSTRUCTION_FILE"
	model="$1"
	instruction="$2"
	[ -f "${instruction}" ] || die "instruction file not found"
	case "${model}" in
	*[!A-Za-z0-9._/-]* | "") die "unsafe model name" ;;
	esac
	setup_git_credentials
	cd /workspace
	exec opencode run --dangerously-skip-permissions --format json \
		--agent build --model "appliance/${model}" "$(cat "${instruction}")"
	;;
shell)
	shift
	setup_git_credentials
	exec "$@"
	;;
help | -h | --help)
	cat <<'EOF'
Usage:
  worker-entrypoint version
  worker-entrypoint git ARGS...
  worker-entrypoint run MODEL INSTRUCTION_FILE
  worker-entrypoint shell COMMAND ARGS...
EOF
	;;
*) die "unknown action: $1" ;;
esac
