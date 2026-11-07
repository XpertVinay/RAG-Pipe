#!/bin/bash
set -e

# Ensure required runtime directories exist
mkdir -p /app/data/uploads /app/data/chroma

# If running as root, fix volume permissions and drop privileges to appuser
if [ "$(id -u)" = "0" ]; then
    chown -R appuser:appgroup /app/data
    chmod -R 775 /app/data
    exec gosu appuser "$@"
else
    exec "$@"
fi
