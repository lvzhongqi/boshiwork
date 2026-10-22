#!/bin/sh
# The image's entry point. The first start in an empty workspace lays it out
# and writes its config; later starts leave both alone. Then the console, or
# whatever orrery subcommand was asked for:
#
#   docker compose up -d                          # the console
#   docker compose run --rm orrery run --name NSPK --dir /work/corpus/academic/NSPK
#
# The console listens on every interface inside the container, which is the
# only way a port mapping can reach it. Who can reach it from outside is decided
# by the mapping, and compose.yaml maps it to the host's 127.0.0.1 alone.
set -eu

WORK=/work

if [ ! -w "$WORK" ]; then
    echo "error: $WORK is not writable by uid $(id -u)." >&2
    echo "  Mount a workspace directory that user can write: on Linux, create" >&2
    echo "  it yourself before the first start and set ORRERY_UID/ORRERY_GID to" >&2
    echo "  your own ids (docker/README.md)." >&2
    exit 1
fi

mkdir -p "$WORK/runs" "$WORK/docs" "$WORK/recordings" "$WORK/corpus"

if [ ! -f "$WORK/config.yaml" ]; then
    cp /usr/local/share/orrery/config.docker.yaml "$WORK/config.yaml"
    chmod 600 "$WORK/config.yaml"
    echo "wrote $WORK/config.yaml; fill in your API key on the console's settings panel"
fi

if [ "$#" -eq 0 ]; then
    exec orrery --config "$WORK/config.yaml" --host 0.0.0.0 --port 8000
fi
exec orrery --config "$WORK/config.yaml" "$@"
