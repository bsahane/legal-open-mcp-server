#!/bin/sh
# Update an LXC/bare-metal checkout from GitHub and restart the service.
#
#   ssh root@<host> 'pct exec 107 -- /opt/legal-mcp/deployment/lxc/deploy.sh'
#
# Fast-forward only: a local edit to a tracked file stops the deploy instead
# of being silently overwritten, so fixes made on the box get noticed and
# committed rather than lost (or left as the only copy).
set -eu
cd "$(dirname "$0")/../.."

before=$(git rev-parse HEAD)
git pull --ff-only --quiet
after=$(git rev-parse HEAD)

if ! git diff --quiet "$before" "$after" -- pyproject.toml uv.lock; then
    echo "Dependencies changed; syncing the virtualenv"
    uv sync --frozen --no-dev
fi

systemctl restart legal-mcp
port=$(sed -n 's/^MCP_PORT=//p' .env 2>/dev/null)
for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -fsS "http://127.0.0.1:${port:-5001}/health" >/dev/null 2>&1; then
        echo "Deployed $(git log --oneline -1)"
        exit 0
    fi
    sleep 2
done
echo "legal-mcp did not become healthy after deploying $after" >&2
journalctl -u legal-mcp -n 30 --no-pager >&2
exit 1
