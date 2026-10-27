#!/usr/bin/env bash
# Browser tests against a fresh local stack: build and start it, create the test
# accounts, trust Caddy's local CA inside the Playwright container (passkeys refuse
# pages with certificate errors), run Playwright, then remove the stack and its data.
#
# Usage, from the repository root on a machine with Docker:  frontend/e2e/run.sh
# Never point this at a stack with real data: `down -v` deletes the volumes.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
# Its own project, so `down -v` below never touches a stack someone is using; on
# its own port, so it runs beside one; and always at localhost, whatever
# deploy/.env says, since the passkey tests expect it.
COMPOSE=(docker compose -p ting-e2e -f "$ROOT/deploy/docker-compose.yml")
export TING_HTTPS_PORT=${E2E_PORT:-8443}
export TING_ADDRESS=https://localhost:$TING_HTTPS_PORT
PLAYWRIGHT_IMAGE=mcr.microsoft.com/playwright:v1.64.1-noble
E2E_PASSWORD="e2e passphrase by the fjord $(date +%s)"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"; "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true' EXIT

"${COMPOSE[@]}" up -d --build
# The app applies migrations before it serves; wait until it answers.
for _ in $(seq 60); do
	curl -fsk -o /dev/null "$TING_ADDRESS/api/health" && break
	sleep 1
done

USERS="e2e-passkey e2e-app e2e-wrong"
for scheme in light dark; do
	for size in desktop phone; do USERS="$USERS e2e-screens-$scheme-$size"; done
done
"${COMPOSE[@]}" exec -T -e E2E_PASSWORD="$E2E_PASSWORD" -e USERS="$USERS" app python - <<'PY'
import os
from sqlalchemy.orm import Session
from app.db import get_engine
from app.policy import SecurityPolicy
from app.roles import Role, grant_role
from app.users import create_user, vet_new_password

policy = SecurityPolicy(breach_check_enabled=False)
with Session(get_engine()) as db:
    for username in os.environ["USERS"].split():
        password = vet_new_password(os.environ["E2E_PASSWORD"], policy, username=username)
        create_user(db, username, "Astrid Fjeld", password)
    # Administrators, a manager, technicians and an auditor for the admin panel,
    # customer and menu tests (the wizard's Administrator has a passkey only).
    for username, name, role in (
        ("e2e-admin", "Eir Admin", Role.ADMINISTRATOR),
        ("e2e-boss", "Bodil Boss", Role.ADMINISTRATOR),
        ("e2e-tech", "Tor Tekniker", Role.TECHNICIAN),
        ("e2e-manager", "Maja Manager", Role.MANAGER),
        ("e2e-tove", "Tove Tekniker", Role.TECHNICIAN),
        ("e2e-auditor", "Aud Auditor", Role.AUDITOR),
        ("e2e-keeper", "Kari Keeper", Role.ADMINISTRATOR),
        ("e2e-mette", "Mette Madsen", Role.ADMINISTRATOR),
        ("e2e-bob", "Bob Bager", Role.TECHNICIAN),
        ("e2e-postmaster", "Pia Post", Role.ADMINISTRATOR),
    ):
        password = vet_new_password(os.environ["E2E_PASSWORD"], policy, username=username)
        grant_role(db, create_user(db, username, name, password), role, actor=None, ip=None)
    db.commit()
PY

"${COMPOSE[@]}" exec -T caddy cat /data/caddy/pki/authorities/local/root.crt >"$WORK/caddy-root.crt"
# A fresh setup token for the wizard test (this replaces the one printed at start).
SETUP_TOKEN=$("${COMPOSE[@]}" exec -T app python -m app.setup | sed -n 's/.*Setup token: //p')

status=0
docker run --rm --network host \
	-e E2E_PASSWORD="$E2E_PASSWORD" \
	-e E2E_SETUP_TOKEN="$SETUP_TOKEN" \
	-e TING_URL="$TING_ADDRESS" \
	-e HOST_UID="$(id -u)" \
	-e NODE_EXTRA_CA_CERTS=/work/caddy-root.crt \
	-v "$ROOT/frontend":/src:ro \
	-v "$WORK":/work \
	"$PLAYWRIGHT_IMAGE" bash -c '
		set -e
		apt-get update -qq >/dev/null && apt-get install -y -qq libnss3-tools >/dev/null
		mkdir -p ~/.pki/nssdb && certutil -d sql:$HOME/.pki/nssdb -N --empty-password
		certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n ting-local-ca -i /work/caddy-root.crt
		cp -r /src /app && cd /app && rm -rf node_modules e2e-results
		npm ci --no-audit --no-fund >/dev/null
		result=0; npx playwright test || result=$?
		cp -r e2e-results /work/ 2>/dev/null || true
		chown -R "$HOST_UID" /work
		exit $result' || status=$?

mkdir -p "$ROOT/frontend/e2e-results"
cp -r "$WORK/e2e-results/." "$ROOT/frontend/e2e-results/" 2>/dev/null || true
exit $status
