#!/bin/sh
# Platform volumes (Fly, Render) are often mounted root-owned. Fix ownership of the data dir,
# then drop to the unprivileged user for everything else.
set -e
if [ "$(id -u)" = "0" ]; then
    mkdir -p "${DATA_DIR:-/data}"
    chown -R askdata:askdata "${DATA_DIR:-/data}"
    exec setpriv --reuid=10001 --regid=10001 --clear-groups "$0" "$@"
fi
python -m app.demo.seed
exec "$@"
