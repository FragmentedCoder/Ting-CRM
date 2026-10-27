#!/bin/sh
# Caddy, with the settings the app writes into the volume shared at
# /etc/caddy/ting: TLS and the admin panel's allowlist (see backend/app/tls.py
# and docs/architecture.md, "HTTPS").
# They're copied into place, and Caddy reloads whenever they change; settings
# that don't load leave Caddy with the ones it had.
set -u

shared=/etc/caddy/ting
config="--config /etc/caddy/Caddyfile --adapter caddyfile"
# What the app writes, each copied to /etc/caddy/active-<name> for the Caddyfile to
# import, or the default from /etc/caddy/default-<name> until there is one.
settings_files="tls.caddy admin-allowlist.caddy"

fingerprint() {
	# shellcheck disable=SC2086 # the names split on purpose
	(cd "$shared" 2>/dev/null && cat $settings_files cert.pem key.pem 2>/dev/null) | sha256sum
}

take_defaults() {
	for name in $settings_files; do
		cp "/etc/caddy/default-$name" "/etc/caddy/active-$name"
	done
}

take_shared() {
	for name in $settings_files; do
		if [ -s "$shared/$name" ]; then
			cp "$shared/$name" "/etc/caddy/active-$name"
		else
			cp "/etc/caddy/default-$name" "/etc/caddy/active-$name"
		fi
	done
}

seen=$(fingerprint)
take_shared
# shellcheck disable=SC2086
if ! caddy validate $config >/dev/null 2>&1; then
	echo "Þing's saved settings for Caddy don't load: using the defaults (Caddy's own certificate, no allowlist)." >&2
	take_defaults
fi

# shellcheck disable=SC2086
caddy run $config &
caddy_pid=$!
trap 'kill -TERM "$caddy_pid" 2>/dev/null' TERM INT

while kill -0 "$caddy_pid" 2>/dev/null; do
	sleep 5 &
	wait $!
	now=$(fingerprint)
	[ "$now" = "$seen" ] && continue
	seen=$now
	for name in $settings_files; do
		cp "/etc/caddy/active-$name" "/etc/caddy/active-$name.before"
	done
	take_shared
	# --force: a new certificate under the same file names is still a change.
	# shellcheck disable=SC2086
	if caddy reload $config --force; then
		echo "Þing's settings for Caddy changed: Caddy reloaded."
	else
		echo "Þing's new settings for Caddy didn't load: Caddy keeps the ones it had." >&2
		for name in $settings_files; do
			mv "/etc/caddy/active-$name.before" "/etc/caddy/active-$name"
		done
	fi
done
wait "$caddy_pid"
