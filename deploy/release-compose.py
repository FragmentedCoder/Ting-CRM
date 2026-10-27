"""The compose file of a release: deploy/docker-compose.yml with each image pinned
by digest instead of built from a checkout. The release workflow runs it:

    python3 deploy/release-compose.py deploy/docker-compose.yml APP_REF CADDY_REF

It replaces the two build blocks it knows, exactly, and fails if either has
changed shape, rather than publish a compose file that still builds.
"""

import re
import sys

APP_BUILD = (
    "    build:\n      context: ../backend\n      args:\n"
    "        # What the build calls itself: set by the installer and the ting command.\n"
    "        TING_VERSION: ${TING_VERSION:-}\n"
)
CADDY_BUILD = "    build:\n      context: ..\n      dockerfile: deploy/caddy.Dockerfile\n"
# registry[:port]/path@sha256:digest
DIGEST = re.compile(r"^[a-z0-9.-]+(:[0-9]+)?(/[a-z0-9._-]+)+@sha256:[0-9a-f]{64}$")


def release_compose(text: str, app_ref: str, caddy_ref: str) -> str:
    for ref in (app_ref, caddy_ref):
        if not DIGEST.match(ref):
            raise SystemExit(f"Not an image pinned by digest: {ref}")
    if text.count(CADDY_BUILD) != 1 or text.count(APP_BUILD) != 3:
        raise SystemExit("The build blocks in docker-compose.yml have changed: update "
                         "deploy/release-compose.py to match.")
    text = text.replace(CADDY_BUILD, f"    image: {caddy_ref}\n")
    text = text.replace(APP_BUILD, f"    image: {app_ref}\n")
    if "build:" in text:
        raise SystemExit("A build block is left in docker-compose.yml.")
    header = ("# Þing's compose file for this release: the images are pinned by digest, and\n"
              "# the installer checks their signatures. Settings go in .env beside it.\n")
    return header + text


if __name__ == "__main__":
    path, app, caddy = sys.argv[1:]
    with open(path) as file:
        sys.stdout.write(release_compose(file.read(), app, caddy))
