#!/bin/sh
set -e

# /app/uploads is a bind-mounted host volume (docker-compose.yml), so the
# image's build-time `chown -R app:app /app` never applies to it at
# runtime — the mount replaces whatever was there. Fix ownership here, as
# root, before dropping to the non-root user, so both pre-existing upload
# directories (from before this container ran non-root) and a completely
# fresh empty volume end up writable by `app`.
mkdir -p /app/uploads
chown -R app:app /app/uploads

exec gosu app "$@"
