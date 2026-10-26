# rclone, for SMB shares (Debian's is too old): its tagged release, built with a
# current Go, which its own binaries can lag behind; Go checks every module against
# its checksum database. The image scan in CI keeps watch.
FROM golang:1.26.10-alpine AS rclone
RUN CGO_ENABLED=0 go install -trimpath \
      -ldflags "-s -w -X github.com/rclone/rclone/fs.Version=v1.75.2" \
      github.com/rclone/rclone@v1.75.2

FROM python:3.13-slim AS base

# Backups: restic from Debian's signed packages, and rclone from above.
RUN apt-get update \
 && apt-get install -y --no-install-recommends restic ca-certificates \
 && rm -rf /var/lib/apt/lists/*
COPY --from=rclone /go/bin/rclone /usr/local/bin/rclone

RUN groupadd --gid 10001 ting \
 && useradd --uid 10001 --gid ting --no-create-home --shell /usr/sbin/nologin ting

WORKDIR /app
COPY pyproject.toml ./
COPY app ./app

# pip has done its job: out it goes, with the old copies of urllib3 and others it
# carries inside.
RUN pip install --no-cache-dir . \
 && pip uninstall -y pip

# /backups: where backups go when the target is this server (a volume, or a folder
# on the host set by TING_BACKUP_DIR). /tls: the TLS settings the app gives Caddy.
RUN mkdir -p /data /backups /tls && chown ting:ting /data /backups /tls

# Which Þing this is, shown to people signed in: the release's tag, or for a build
# from a checkout what git calls that commit. Last, so a new one rebuilds nothing.
ARG TING_VERSION=
ENV TING_VERSION=${TING_VERSION}

USER ting
EXPOSE 8000

# Trust X-Forwarded-For from any peer: the app port is published to nobody but Caddy
# on the internal network, and Caddy replaces the header for untrusted clients.
# app.setup prints a fresh setup token to the log while setup is pending; app.tls
# gives Caddy the TLS settings that are saved.
CMD ["sh", "-c", "python -m app.migrate && python -m app.setup && python -m app.tls && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'"]
