FROM node:22-slim AS build
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Caddy itself, with the DNS providers that Let's Encrypt's DNS challenge can use
# (Cloudflare, and RFC 2136 for an organisation's own DNS server), pinned, built
# with a current Go and fixed dependencies Caddy's own release lacks (golang.org/x/net
# 0.60 for CVE-2026-78669); the image scan in CI keeps watch. Go checks every module
# against its checksum database.
FROM golang:1.26.10-alpine AS caddy
RUN go install github.com/caddyserver/xcaddy/cmd/xcaddy@v0.4.7 \
 && xcaddy build v2.11.7 --output /usr/bin/caddy \
      --with github.com/caddy-dns/cloudflare@v0.2.4 \
      --with github.com/caddy-dns/rfc2136@v1.0.0 \
      --replace golang.org/x/net=golang.org/x/net@v0.60.0

FROM caddy:2.11.7-alpine
# Alpine's fixes since the image was made.
RUN apk upgrade --no-cache
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy
COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY deploy/caddy-start.sh /usr/local/bin/caddy-start
# Until Þing says otherwise: Caddy's own certificate authority, and no allowlist.
RUN printf 'tls internal\n' > /etc/caddy/default-tls.caddy \
 && printf '# The admin panel allowlist is off.\n' > /etc/caddy/default-admin-allowlist.caddy
COPY --from=build /app/build /srv
CMD ["/usr/local/bin/caddy-start"]
