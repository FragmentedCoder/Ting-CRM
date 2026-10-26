#!/usr/bin/env bash
# Tests for the ting command's own logic, without Docker:  deploy/ting.test.sh
# (what it does with Docker is tried against a real stack).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "${WORK}"' EXIT

failures=0
check() {
	local name=$1
	shift
	if "$@"; then
		printf 'ok    %s\n' "${name}"
	else
		printf 'FAIL  %s\n' "${name}"
		failures=$((failures + 1))
	fi
}

# A checkout of its own, with the command in its deploy folder.
mkdir -p "${WORK}/repo/deploy"
cp "${HERE}/ting" "${WORK}/repo/deploy/ting"
git -C "${WORK}/repo" init --quiet
git -C "${WORK}/repo" -c user.name=t -c user.email=t@example.invalid commit --quiet --allow-empty -m start
ting() { TING_HOME="${WORK}/home" "${WORK}/repo/deploy/ting" "$@"; }

for command in status logs "start | stop | restart" backup restore-test restore update "keys rotate" \
	"admin reset-allowlist" "admin reset-certificate" setup-token; do
	check "help lists ${command}" grep -q "^  ${command}" <(ting help)
done
unknown() { ! ting format-disk >/dev/null 2>&1 && [[ $(ting format-disk 2>&1 >/dev/null | head -1) == Usage* ]]; }
check "an unknown command shows the usage and fails" unknown
check "keys says how it's used" grep -q "Usage: ting keys rotate" <(ting keys spin 2>&1 || true)
check "admin says what there is" grep -q "reset-allowlist | reset-certificate" <(ting admin nuke 2>&1 || true)

# shellcheck source=deploy/ting
. "${WORK}/repo/deploy/ting"
set +e
check "with no .env, the address is localhost" test "$(address)" = "https://localhost"
printf 'TING_ADDRESS=https://ting.example.internal:8443\n' >"${WORK}/repo/deploy/.env"
check "the address comes from .env" test "$(address)" = "https://ting.example.internal:8443"
check "the version names the commit" grep -qE '^Þing [0-9a-f]{7,} \([0-9]{4}-[0-9]{2}-[0-9]{2}\)$' <(version)
printf 'v1.2.3\n' >"${WORK}/repo/deploy/VERSION"
check "installed from a release, the version is the release's" test "$(version)" = "Þing v1.2.3"
check "  and update knows it" from_release
# docker stands in, saying which version a build would be told.
# shellcheck disable=SC2317 # called by compose
docker() { printf '%s' "${TING_VERSION}"; }
check "  and builds nothing, so tells no version to a build" test -z "$(compose ps)"
rm "${WORK}/repo/deploy/VERSION"
check "a build from a checkout calls itself what git calls the commit" \
	test "$(compose up -d --build)" = "$(git -C "${WORK}/repo" rev-parse --short HEAD)"
git -C "${WORK}/repo" -c user.name=t -c user.email=t@example.invalid commit --quiet --allow-empty -m next
git -C "${WORK}/repo" tag v9.9.9
check "  the commit an update moved to, not the one before" test "$(compose up -d --build)" = "v9.9.9"
unset -f docker

# Copying the data aside: what docker hands over must be the archive, whole.
mkdir -p "${WORK}/data"
: >"${WORK}/data/ting.db"
archive() { tar -C "${WORK}/data" -czf - ./ting.db; }
refused() { ! copy_data_to "$1" 2>/dev/null && test ! -e "$1"; }
# shellcheck disable=SC2317 # called by compose
docker() {
	echo "$*" >>"${WORK}/calls"
	case " $* " in
	*" build "*) echo "#1 [internal] load build definition from Dockerfile" ;;
	*" run "*) archive ;;
	esac
}
copied() { copy_data_to "$1" 2>/dev/null; }
check "the data's copy is kept when it's the archive" copied "${WORK}/copy.tar.gz"
check "  the tools image built first, apart" grep -qE "build .*tools" <(head -1 "${WORK}/calls")
check "  its build log kept out of the copy" grep -qx './ting.db' <(tar -tzf "${WORK}/copy.tar.gz")
# shellcheck disable=SC2317
docker() { case " $* " in *" run "*) printf '#1 [internal] load build definition\n' && archive ;; esac; }
check "a copy with anything else in it is refused" refused "${WORK}/noisy.tar.gz"
# shellcheck disable=SC2317
docker() { case " $* " in *" run "*) tar -C "${WORK}" -czf - ./calls ;; esac; }
check "a copy without the database is refused" refused "${WORK}/empty.tar.gz"
unset -f docker

# Which release is newest, with GitHub's answers made up: curl stands in, answering
# /releases/latest with LATEST and the list of releases with LISTED ("status tag").
# shellcheck disable=SC2317 # called by newest_release
curl() {
	local out="" url="" answer
	while [[ $# -gt 0 ]]; do
		case "$1" in
		-o | -w) [[ "$1" == -o ]] && out=$2; shift 2 ;;
		-*) shift ;;
		*) url=$1; shift ;;
		esac
	done
	case "${url}" in
	*/releases/latest) answer=${LATEST} ;;
	*/releases\?per_page=1) answer=${LISTED} ;;
	*) answer=404 ;;
	esac
	[[ "${answer}" == 000 ]] && { printf 000; return 7; }
	printf '[\n  {\n    "tag_name": "%s",\n    "prerelease": true\n  }\n]\n' "${answer#* }" >"${out}"
	printf '%s' "${answer%% *}"
}
picks() { [[ "$(LATEST=$1 LISTED=$2 newest_release)" == "$3" ]]; }
check "update moves to the newest full release" picks "200 v1.0.0" "200 v1.1.0-rc.1" v1.0.0
check "  while there's none yet, the newest pre-release" picks 404 "200 v1.1.0-rc.1" v1.1.0-rc.1
check "  nothing while GitHub doesn't answer, not a pre-release instead" picks 000 "200 v1.1.0-rc.1" ""
check "  nor when it refuses (rate limited)" picks 403 "200 v1.1.0-rc.1" ""
check "  nor when there's no release at all" picks 404 "200 " ""
unset -f curl

touch "${WORK}/repo/stray-file"
check "update refuses a checkout with changes of its own" \
	grep -q "has changes of its own" <(ting update 2>&1 || true)
check "  before touching the data" test ! -e "${WORK}/home/rollback/data-"*

if [[ ${failures} -gt 0 ]]; then
	echo "${failures} failed."
	exit 1
fi
echo "All passed."
