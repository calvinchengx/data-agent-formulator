#!/bin/sh
# Start Data Formulator with this repository's plugin directory, and nothing else.
#
# DF_PLUGIN_DIR must be absolute: Data Formulator resolves it once, at import,
# from whatever working directory the server happened to start in.
set -e
cd "$(dirname "$0")/.."
ROOT=$(pwd)
# The loader's own settings, so the parameter form arrives pre-filled with a
# working local configuration rather than with placeholders. Sourced FIRST:
# `DATA_FORMULATOR_HOME=` is deliberately empty in the template, and an export
# placed above this would be silently clobbered by it -- which is exactly what
# happened the first time this script was run.
[ -f "$ROOT/.env" ] && { set -a; . "$ROOT/.env"; set +a; } || { set -a; . "$ROOT/.env.example"; set +a; }
# Absolute, and after the template: Data Formulator resolves it once, at import,
# from whatever directory the server started in.
export DF_PLUGIN_DIR="$ROOT/plugin"
exec "$ROOT/.venv/bin/data_formulator" "$@"
