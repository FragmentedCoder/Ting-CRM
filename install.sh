#!/usr/bin/env bash
# Þing installer: check the host, install Docker Engine, put the master key in
# place, write Þing's address, then start Þing and print the setup token for
# the web wizard.
#
#   curl -fsSL https://raw.githubusercontent.com/FragmentedCoder/Ting-CRM/main/install.sh | sudo bash
#   sudo bash install.sh [--address https://ting.example.internal]
#   sudo bash install.sh --restore-master-key    (a new server, from the recovery kit)
#
# From a release it downloads the release's files into /opt/ting, checks them and
# every image against the release workflow's signatures, and pulls the images;
# from a checkout of the repository it builds them. Run it again any time: what's
# in place is kept. --restore-master-key stops before starting Þing, so a backup
# can be restored first.
set -euo pipefail

DEPLOY_DIR=$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" && pwd)
# Run as the repository's install.sh: the checkout's deploy folder is beside it.
if [[ -f "${DEPLOY_DIR}/deploy/docker-compose.yml" ]]; then DEPLOY_DIR="${DEPLOY_DIR}/deploy"; fi
TING_HOME="${TING_HOME:-/opt/ting}"
TING_ETC="${TING_ETC:-/etc/ting}"
ENV_FILE="${ENV_FILE:-}"
BIN_DIR="${BIN_DIR:-/usr/local/bin}"
MIN_CPU=4
MIN_RAM_MB=7800
MIN_DISK_GB=90
# The app containers' user, which reads the master key.
APP_UID=10001

# Releases: where they come from, and who signs them. A release's own installer
# carries its version here (the release workflow writes it); from a checkout it's
# empty and Þing is built there, and from main's install.sh it's the newest.
TING_REPOSITORY="${TING_REPOSITORY:-FragmentedCoder/Ting-CRM}"
TING_RELEASE=${TING_RELEASE:-}
TING_RELEASE_URL="${TING_RELEASE_URL:-https://github.com/${TING_REPOSITORY}/releases/download}"
# Images re-signed with an organisation's own key are checked against it instead
# (the key alone: such signatures aren't in the public transparency log).
TING_COSIGN_KEY="${TING_COSIGN_KEY:-}"
# As the release names them (no leading dot: GitHub renames such files), and as
# they're kept in Þing's folder.
RELEASE_ASSETS="docker-compose.yml install.sh ting env.example"
RELEASE_FILES="docker-compose.yml install.sh ting .env.example"
COSIGN_VERSION=v3.1.3
COSIGN_SHA256_AMD64=4629c757b7618056f8ddd7e2625ae9fdd94c0372a65049520bc7d9df9efc7f71
COSIGN_SHA256_ARM64=c5d324e091826b0d7a78eb16fef316450b4eb9aaec045611c08ba06f5e73220a

log() { printf '==> %s\n' "$1"; }
warn() { printf 'WARNING: %s\n' "$1" >&2; }
die() {
	printf 'ERROR: %s\n' "$1" >&2
	exit 1
}

usage() {
	# Piped (curl | bash), there's no file to read the help from.
	[[ -n "${BASH_SOURCE[0]:-}" ]] && sed -n '2,15s/^# \{0,1\}//p' "${BASH_SOURCE[0]}"
}

# From a checkout, or from a release.
from_checkout() {
	[[ -f "${DEPLOY_DIR}/docker-compose.yml" ]] && grep -q '^    build:' "${DEPLOY_DIR}/docker-compose.yml"
}

env_file() { printf '%s' "${ENV_FILE:-${DEPLOY_DIR}/.env}"; }

# A question for whoever runs this, even with the script itself on stdin (curl | bash).
ask() {
	local prompt=$1 secret=${2:-} answer=""
	local options=(-p "${prompt}")
	if [[ -n "${secret}" ]]; then options=(-s -p "${prompt}"); fi
	if [[ -t 0 ]]; then
		read -r "${options[@]}" answer
	elif [[ -r /dev/tty ]]; then
		read -r "${options[@]}" answer </dev/tty
	fi
	if [[ -n "${secret}" ]]; then echo >&2; fi
	printf '%s' "${answer}"
}

check_os() {
	if [[ ! -r /etc/os-release ]]; then
		die "Cannot read /etc/os-release; this installer targets Ubuntu Server LTS."
	fi
	# shellcheck source=/dev/null
	. /etc/os-release
	if [[ "${ID:-}" != "ubuntu" ]]; then
		die "Þing targets Ubuntu Server LTS; found ID=${ID:-unknown}."
	fi
	log "OS: ${PRETTY_NAME:-Ubuntu}"
}

check_resources() {
	local cpu ram_mb disk_gb
	cpu=$(nproc)
	ram_mb=$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo)
	disk_gb=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')

	log "Resources: ${cpu} vCPU, ${ram_mb} MB RAM, ${disk_gb} GB free on /."

	if [[ "${cpu}" -lt "${MIN_CPU}" ]]; then warn "Fewer than ${MIN_CPU} vCPU; Þing will be slow under load."; fi
	if [[ "${ram_mb}" -lt "${MIN_RAM_MB}" ]]; then warn "Less than ~8 GB RAM; ClamAV alone needs about 2 GB."; fi
	if [[ "${disk_gb}" -lt "${MIN_DISK_GB}" ]]; then warn "Less than ${MIN_DISK_GB} GB free; grow the disk before storing real data."; fi
}

install_docker() {
	if command -v docker >/dev/null 2>&1; then
		log "Docker is already installed."
		return
	fi
	log "Installing Docker Engine from Docker's own repository."
	install -m 0755 -d /etc/apt/keyrings
	curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
	chmod a+r /etc/apt/keyrings/docker.asc
	# shellcheck source=/dev/null
	. /etc/os-release
	echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
		>/etc/apt/sources.list.d/docker.list
	apt-get update -qq
	apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin
}

create_directories() {
	install -d -m 0750 "${TING_HOME}"
	# Owned by the app container's non-root UID, not actual root: the app
	# reads the master key directly, and it never runs as root (see
	# docs/architecture.md's hardening section).
	install -d -m 0700 "${TING_ETC}"
	chown "${APP_UID}:${APP_UID}" "${TING_ETC}" # an existing folder too
	log "${TING_HOME} and ${TING_ETC} are in place."
}

# Write a key file only the app's user can read, whole or not at all.
write_key_file() {
	local key_file=$1 source=$2
	(umask 077 && cp "${source}" "${key_file}.new")
	chown "${APP_UID}:${APP_UID}" "${key_file}.new" 2>/dev/null || [[ "${EUID}" -ne 0 ]]
	chmod 0600 "${key_file}.new"
	mv "${key_file}.new" "${key_file}"
}

generate_master_key() {
	local key_file="${TING_ETC}/master.key" fresh
	if [[ -f "${key_file}" ]]; then
		log "Master key already exists; leaving it alone."
		return
	fi
	log "Generating the master key."
	fresh=$(mktemp)
	head -c 32 /dev/urandom >"${fresh}"
	write_key_file "${key_file}" "${fresh}"
	rm -f "${fresh}"
}

# A key as the recovery kit writes it (base32 in groups of four; spaces, dashes and
# case don't matter) to its 32 bytes, into the file named.
kit_to_key() {
	local text=$1 out=$2 compact
	compact=$(printf '%s' "${text}" | tr -d ' \t\r\n-' | tr '[:lower:]' '[:upper:]')
	if [[ ! "${compact}" =~ ^[A-Z2-7]{52}$ ]]; then
		echo "That isn't a key from the recovery kit: it has 13 groups of four letters and digits (2-7)."
		return 1
	fi
	printf '%s====' "${compact}" | base32 -d >"${out}" 2>/dev/null || {
		echo "That key doesn't decode; check it against the recovery kit."
		return 1
	}
	if [[ $(stat -c %s "${out}") -ne 32 ]]; then
		echo "That key doesn't decode to 32 bytes; check it against the recovery kit."
		return 1
	fi
}

# Put the kit's master key in place, from KIT_MASTER_KEY or typed (not shown).
restore_master_key() {
	local key_file="${TING_ETC}/master.key" text="${KIT_MASTER_KEY:-}" decoded problem
	if [[ -z "${text}" ]]; then
		text=$(ask "Master key from the recovery kit: " secret)
	fi
	decoded=$(mktemp)
	if ! problem=$(kit_to_key "${text}" "${decoded}"); then
		rm -f "${decoded}"
		die "${problem}"
	fi
	if [[ -f "${key_file}" ]]; then
		if cmp -s "${decoded}" "${key_file}"; then
			rm -f "${decoded}"
			log "That master key is already in place."
			return
		fi
		rm -f "${decoded}"
		die "A different master key is already at ${key_file}. If it belongs to nothing, move it away and run this again."
	fi
	write_key_file "${key_file}" "${decoded}"
	rm -f "${decoded}"
	log "Put the recovery kit's master key in place."
}

valid_address() {
	[[ "$1" =~ ^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?$ ]]
}

# Þing's address goes in .env (passkeys are tied to it, so it's asked for once).
configure_address() {
	local address=$1 env
	env=$(env_file)
	if [[ -f "${env}" ]] && grep -q '^TING_ADDRESS=' "${env}"; then
		log "Using the address in ${env}: $(sed -n 's/^TING_ADDRESS=//p' "${env}")"
		return
	fi
	if [[ -z "${address}" ]]; then
		local suggested
		suggested="https://$(hostname -f 2>/dev/null || hostname)"
		address=$(ask "Þing's address, as people will type it [${suggested}]: ")
		address=${address:-${suggested}}
	fi
	valid_address "${address}" || die "The address must look like https://ting.example.internal (a port may follow)."
	sed "s|^TING_ADDRESS=.*|TING_ADDRESS=${address}|" "${DEPLOY_DIR}/.env.example" >"${env}"
	if [[ "${address}" =~ :([0-9]+)$ ]]; then
		printf 'TING_HTTPS_PORT=%s\n' "${BASH_REMATCH[1]}" >>"${env}"
	fi
	if [[ "${TING_ETC}" != /etc/ting ]]; then
		printf 'TING_ETC=%s\n' "${TING_ETC}" >>"${env}"
	fi
	log "Wrote ${env} with the address ${address}."
}

# Releases

install_cosign() {
	export PATH="${BIN_DIR}:${PATH}" # where it goes, first
	if [[ "$(cosign version 2>/dev/null | sed -n 's/^GitVersion: *//p')" == "${COSIGN_VERSION}" ]]; then
		return
	fi
	local arch sum download
	arch=$(dpkg --print-architecture)
	case "${arch}" in
	amd64) sum=${COSIGN_SHA256_AMD64} ;;
	arm64) sum=${COSIGN_SHA256_ARM64} ;;
	*) die "No cosign build is pinned for ${arch}." ;;
	esac
	log "Installing cosign ${COSIGN_VERSION}, which checks Þing's signatures."
	download=$(mktemp)
	curl -fsSLo "${download}" "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-${arch}"
	echo "${sum}  ${download}" | sha256sum -c --quiet - || die "The cosign download doesn't match its pinned checksum."
	install -m 0755 "${download}" "${BIN_DIR}/cosign"
	rm -f "${download}"
}

# Who signs a release: the repository's release workflow, for that very tag.
signer() {
	local version=$1
	if [[ -n "${TING_COSIGN_KEY}" ]]; then
		printf '%s\n' --key "${TING_COSIGN_KEY}" --insecure-ignore-tlog=true
	else
		printf '%s\n' --certificate-identity \
			"https://github.com/${TING_REPOSITORY}/.github/workflows/release.yml@refs/tags/${version}" \
			--certificate-oidc-issuer https://token.actions.githubusercontent.com
	fi
}

# The newest full release; while there's none yet, the newest pre-release. Nothing
# when GitHub doesn't answer plainly: never a pre-release for a release unseen.
newest_release() {
	local releases="https://api.github.com/repos/${TING_REPOSITORY}/releases" answer status
	answer=$(mktemp)
	status=$(curl -sSL -o "${answer}" -w '%{http_code}' "${releases}/latest") || status=000
	if [[ "${status}" == 404 ]]; then
		status=$(curl -sSL -o "${answer}" -w '%{http_code}' "${releases}?per_page=1") || status=000
	fi
	if [[ "${status}" == 200 ]]; then
		sed -n 's/^ *"tag_name": *"\([^"]*\)".*/\1/p' "${answer}" | head -1
	fi
	rm -f "${answer}"
}

# A release's files into a folder, each checked against the signed checksums.
fetch_release() {
	local version=$1 into=$2 name signed
	[[ "${version}" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.]+)?$ ]] || die "${version} isn't a release."
	mapfile -t signed < <(signer "${version}")
	install -d -m 0750 "${into}"
	for name in ${RELEASE_ASSETS} SHA256SUMS SHA256SUMS.sigstore.json; do
		curl -fsSLo "${into}/${name}" "${TING_RELEASE_URL}/${version}/${name}" ||
			die "Couldn't download ${name} of Þing ${version}."
	done
	cosign verify-blob --bundle "${into}/SHA256SUMS.sigstore.json" "${signed[@]}" \
		"${into}/SHA256SUMS" >/dev/null 2>&1 ||
		die "Þing ${version}'s checksums aren't signed by its release workflow: nothing was changed."
	for name in ${RELEASE_ASSETS}; do
		grep -q " ${name}\$" "${into}/SHA256SUMS" || die "Þing ${version}'s checksums leave out ${name}."
	done
	(cd "${into}" && grep -E ' (docker-compose\.yml|install\.sh|ting|env\.example)$' SHA256SUMS |
		sha256sum -c --quiet -) || die "A file of Þing ${version} doesn't match its signed checksum."
	mv "${into}/env.example" "${into}/.env.example"
	chmod 0755 "${into}/install.sh" "${into}/ting"
	printf '%s\n' "${version}" >"${into}/VERSION"
}

# Every image a compose file names: pinned by digest, and signed for that release.
verify_images() {
	local compose_file=$1 version=$2 ref signed
	mapfile -t signed < <(signer "${version}")
	# None named would pass every check below: a release always runs images.
	grep -q '^ *image: ' "${compose_file}" || die "Þing ${version}'s compose file names no images."
	! grep -q '^ *build:' "${compose_file}" || die "Þing ${version}'s compose file builds images instead."
	while read -r ref; do
		[[ "${ref}" == *@sha256:* ]] || die "${ref} isn't pinned by digest."
		cosign verify "${signed[@]}" "${ref}" >/dev/null 2>&1 ||
			die "The image ${ref} isn't signed for Þing ${version}: nothing was started."
	done < <(sed -n 's/^ *image: *//p' "${compose_file}" | sort -u)
	log "Every image of Þing ${version} is signed for it."
}

# The release's files into Þing's folder (its .env stays), and run from there.
install_release() {
	local version=${TING_RELEASE:-} staging name mode
	if [[ -z "${version}" ]]; then
		version=$(newest_release)
		[[ -n "${version}" ]] || die "No Þing release found to install: GitHub didn't answer, or there's none yet."
	fi
	if [[ "${version}" == *-* ]]; then warn "Þing ${version} is a pre-release: for trying out, not for real data."; fi
	install_cosign
	staging=$(mktemp -d)
	fetch_release "${version}" "${staging}"
	verify_images "${staging}/docker-compose.yml" "${version}"
	install -d -m 0750 "${TING_HOME}"
	for name in ${RELEASE_FILES} VERSION; do
		mode=0640
		if [[ "${name}" == install.sh || "${name}" == ting ]]; then mode=0755; fi
		install -m "${mode}" "${staging}/${name}" "${TING_HOME}/${name}"
	done
	rm -rf "${staging}"
	DEPLOY_DIR=${TING_HOME}
	log "Þing ${version} is in ${TING_HOME}."
}

# The ting command, for what the web UI can't do (`ting help`).
link_command() {
	ln -sfn "${DEPLOY_DIR}/ting" "${BIN_DIR}/ting"
	log "Linked ${BIN_DIR}/ting; run ting help to see what it does."
}

compose() {
	# Built from a checkout, Þing calls itself what git calls the commit.
	local repo version=""
	if from_checkout; then
		repo=$(dirname "${DEPLOY_DIR}")
		version=$(git -c safe.directory="${repo}" -C "${repo}" describe --tags --always 2>/dev/null) || true
	fi
	TING_VERSION=${version} docker compose --project-directory "${DEPLOY_DIR}" \
		-f "${DEPLOY_DIR}/docker-compose.yml" "$@"
}

start_stack() {
	local address host port
	address=$(sed -n 's/^TING_ADDRESS=//p' "$(env_file)")
	host=$(sed -E 's|^https://([^:/]+).*|\1|' <<<"${address}")
	port=$(sed -nE 's|^https://[^:/]+:([0-9]+)$|\1|p' <<<"${address}")
	port=${port:-443}

	if from_checkout; then
		log "Building and starting Þing (the first build takes a few minutes)."
		compose up -d --build
	else
		log "Pulling and starting Þing."
		compose pull --quiet
		compose up -d
	fi
	log "Waiting for Þing to answer at ${address}."
	for _ in $(seq 120); do
		# Through Caddy on this server, whatever the name resolves to here.
		if curl -fsk --resolve "${host}:${port}:127.0.0.1" -o /dev/null "${address}/api/health"; then
			log "Þing is up."
			local said
			said=$(compose exec -T app python -m app.setup)
			if grep -q "Setup token" <<<"${said}"; then
				printf '%s\n' "${said}"
				log "Open ${address}/setup and enter the setup token above."
				log "Until you choose another certificate in the wizard, Þing's own authority signs"
				log "it: install ${address}/ting-root.crt as a trusted root on each computer."
			else
				log "Þing is set up already, at ${address}."
			fi
			log "ting status shows how it is, and ting help what else it does."
			return
		fi
		sleep 2
	done
	die "Þing didn't answer within four minutes. See: ting logs app caddy"
}

main() {
	local address="" restore=false
	while [[ $# -gt 0 ]]; do
		case "$1" in
		--address)
			[[ $# -ge 2 ]] || die "--address needs the address."
			address=$2
			shift 2
			;;
		--address=*)
			address=${1#--address=}
			shift
			;;
		--restore-master-key)
			restore=true
			shift
			;;
		# ting update: a release's files into a folder, checked, images and all.
		--fetch)
			[[ $# -eq 3 ]] || die "Usage: install.sh --fetch VERSION FOLDER"
			install_cosign
			fetch_release "$2" "$3"
			verify_images "$3/docker-compose.yml" "$2"
			exit 0
			;;
		-h | --help)
			usage
			exit 0
			;;
		*) die "Unknown option $1 (see --help)." ;;
		esac
	done
	[[ "${EUID}" -eq 0 ]] || die "Run this installer as root (sudo)."
	if [[ -n "${address}" ]]; then
		valid_address "${address}" || die "The address must look like https://ting.example.internal (a port may follow)."
	fi

	check_os
	check_resources
	install_docker
	create_directories
	if ! from_checkout; then install_release; fi
	if [[ "${restore}" == true ]]; then
		restore_master_key
	else
		generate_master_key
	fi
	configure_address "${address}"
	link_command

	if [[ "${restore}" == true ]]; then
		log "Next, restore a backup with the recovery kit's backup key:"
		log "  ting restore"
		return
	fi
	start_stack
}

# Sourced by deploy/install.test.sh, which tests the functions on their own. Piped
# (curl | bash) there's no BASH_SOURCE at all: set -u would stop at it.
if [[ "${BASH_SOURCE[0]:-$0}" == "$0" ]]; then
	main "$@"
fi
